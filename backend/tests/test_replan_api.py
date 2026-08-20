"""The M2 flagship: "a doctor calls in sick at 9 AM with 40 booked patients"."""

import pytest


@pytest.fixture
def auth(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


def clinic_row(client, auth, badge):
    rows = client.get("/api/v1/scheduling/clinic", headers=auth).json()
    return next(r for r in rows if r["badge_id"] == badge)


def test_an_absent_doctor_has_their_clinic_redistributed(client, auth, fresh_badge, clinic_list):
    badge = fresh_badge("HP-DOC-1001")
    booked = clinic_list(badge, 40)  # the number PRD §M2 names
    before = clinic_row(client, auth, badge)
    assert before["booked"] == booked > 0
    assert before["unavailable_reason"] is None

    r = client.post(
        f"/api/v1/presence/{before['doctor_id']}/override",
        headers=auth,
        json={"state": "ON_LEAVE", "reason": "Called in sick at 09:05"},
    )
    assert r.status_code == 200

    after = clinic_row(client, auth, badge)
    assert after["booked"] == 0, "nobody should still be waiting for an absent doctor"
    assert "leave" in after["unavailable_reason"]

    runs = client.get("/api/v1/scheduling/plan-runs?limit=1", headers=auth).json()
    assert runs, "a replan must leave evidence in plan_runs"
    run = runs[0]
    assert run["trigger"] == "PRESENCE_CHANGE", "the override should trigger it, not a human"
    assert run["solver_status"] in ("OPTIMAL", "FEASIBLE")
    assert run["moved_count"] == before["booked"], "with room in the department, nobody is dropped"
    assert run["duration_ms"] < 5000, "PRD §M2 budget"


def test_a_manual_replan_can_be_dry_run(client, auth, fresh_badge, clinic_list):
    badge = fresh_badge("HP-DOC-1014")
    clinic_list(badge, 8)
    row = clinic_row(client, auth, badge)
    r = client.post(
        f"/api/v1/scheduling/replan/{row['doctor_id']}?dry_run=true", headers=auth
    ).json()
    assert r["duration_ms"] < 5000
    # nothing actually moved
    assert clinic_row(client, auth, badge)["booked"] == row["booked"]


def test_replan_is_admin_only(client, auth):
    from app.models import UserRole
    from app.security import make_token

    row = client.get("/api/v1/scheduling/clinic", headers=auth).json()[0]
    staff = make_token("00000000-0000-0000-0000-000000000000", UserRole.STAFF)
    r = client.post(
        f"/api/v1/scheduling/replan/{row['doctor_id']}",
        headers={"Authorization": f"Bearer {staff}"},
    )
    assert r.status_code == 403


def test_plan_runs_requires_auth(client):
    assert client.get("/api/v1/scheduling/plan-runs").status_code == 401


def test_a_patient_who_cannot_be_seated_is_pending_not_cancelled(
    client, auth, fresh_badge, clinic_list
):
    """A silent CANCELLED means the patient finds out by turning up to an empty clinic."""
    badge = fresh_badge("HP-DOC-1003")
    clinic_list(badge, 12)
    row = clinic_row(client, auth, badge)

    # take the colleagues' seats away so there is genuinely nowhere to move anyone
    import os

    from sqlalchemy import NullPool, text
    from sqlalchemy.ext.asyncio import create_async_engine

    async def _set_colleague_slots(status_value: str):
        """Scoped to this one department, and put back in a finally — a test that
        leaves every slot in the database BLOCKED quietly breaks `make demo`."""
        engine = create_async_engine(os.environ["DATABASE_URL"], poolclass=NullPool)
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    f"update slots set status='{status_value}' where starts_at >= now()"
                    " and department_id = (select department_id from doctors"
                    " where badge_id = :b)"
                    " and doctor_id <> (select id from doctors where badge_id = :b)"
                ),
                {"b": badge},
            )
        await engine.dispose()

    client.portal.call(_set_colleague_slots, "BLOCKED")
    try:
        r = client.post(
            f"/api/v1/presence/{row['doctor_id']}/override",
            headers=auth,
            json={"state": "ON_LEAVE", "reason": "nowhere to move anyone"},
        )
        assert r.status_code == 200
        pending = client.get("/api/v1/scheduling/pending", headers=auth).json()
        assert len(pending) >= 12, "everyone unseated should be visible as pending"
        assert all(
            p["patient_name"] and p["patient_phone"] for p in pending
        ), "staff need to be able to actually call these people"
    finally:
        client.portal.call(_set_colleague_slots, "OPEN")


def test_a_seat_held_by_a_likely_no_show_is_offered_to_the_solver(client, auth, fresh_badge):
    """The mechanism, not the seed: a capped feature nobody ever sees run is
    indistinguishable from a broken one. (`make seed` producing the risk profile is
    checked by /demo-check, which runs against a freshly seeded database.)"""
    import os

    from sqlalchemy import NullPool, text
    from sqlalchemy.ext.asyncio import create_async_engine

    badge = fresh_badge("HP-DOC-1002")

    async def _probe() -> int:
        from datetime import UTC, datetime, timedelta

        from sqlalchemy.ext.asyncio import async_sessionmaker

        from app.models import Doctor
        from app.services.scheduling import OVERBOOK_NOSHOW_THRESHOLD, _overbookable_slots

        engine = create_async_engine(os.environ["DATABASE_URL"], poolclass=NullPool)
        session = async_sessionmaker(engine)
        async with session() as db:
            # build the situation rather than hunt for it: one colleague's seat, taken
            # by a patient the model thinks will not turn up
            seat = (
                await db.execute(
                    text(
                        "select s.id from slots s where s.starts_at >= now()"
                        " and s.doctor_id <> (select id from doctors where badge_id=:b)"
                        " and s.department_id = (select department_id from doctors"
                        " where badge_id=:b) order by s.starts_at limit 1"
                    ),
                    {"b": badge},
                )
            ).scalar_one_or_none()
            if seat is None:
                return -1
            await db.execute(
                text(
                    "insert into appointments (patient_id, slot_id, hospital_id,"
                    " department_id, channel, priority_class, status, noshow_prob)"
                    " select (select id from patients limit 1), :s, d.hospital_id,"
                    " d.department_id, 'PWA', 'GENERAL', 'BOOKED', :p"
                    " from doctors d where d.badge_id = :b"
                ),
                {"s": seat, "p": OVERBOOK_NOSHOW_THRESHOLD + 0.05, "b": badge},
            )
            await db.execute(text("update slots set status='FULL' where id = :s"), {"s": seat})
            await db.commit()

            doctor = (
                await db.execute(
                    text("select id from doctors where badge_id=:b").bindparams(b=badge)
                )
            ).scalar_one()
            doc = await db.get(Doctor, doctor)
            now = datetime.now(UTC)
            offered = await _overbookable_slots(db, doc, now, now + timedelta(hours=24))
            capacities = [s.capacity for s in offered]
            await db.rollback()
        await engine.dispose()
        return max(capacities, default=0)

    assert client.portal.call(_probe) == 2, "a likely-no-show seat should hold one more"

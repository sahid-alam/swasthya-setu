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

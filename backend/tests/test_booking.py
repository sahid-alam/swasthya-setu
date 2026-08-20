"""Channel-agnostic booking — PRD §M3. Every channel lands here, so the rules are
tested once, here, rather than per channel."""

import pytest

from app.models import Channel


@pytest.fixture
def auth(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


@pytest.fixture
def department(client, auth):
    rows = client.get("/api/v1/scheduling/clinic", headers=auth).json()
    board = client.get("/api/v1/presence", headers=auth).json()
    name = rows[0]["department"]
    import os

    from sqlalchemy import NullPool, text
    from sqlalchemy.ext.asyncio import create_async_engine

    async def _lookup():
        engine = create_async_engine(os.environ["DATABASE_URL"], poolclass=NullPool)
        async with engine.begin() as conn:
            dep = (
                await conn.execute(
                    text("select id from departments where name = :n limit 1"), {"n": name}
                )
            ).scalar_one()
        await engine.dispose()
        return str(dep)

    assert board is not None
    return client.portal.call(_lookup)


@pytest.fixture
def a_patient(client):
    import os

    from sqlalchemy import NullPool, text
    from sqlalchemy.ext.asyncio import create_async_engine

    async def _one():
        engine = create_async_engine(os.environ["DATABASE_URL"], poolclass=NullPool)
        async with engine.begin() as conn:
            pid = (await conn.execute(text("select id from patients limit 1"))).scalar_one()
        await engine.dispose()
        return str(pid)

    return client.portal.call(_one)


def test_search_returns_only_seats_that_can_actually_be_given(client, auth, department):
    offers = client.get(
        f"/api/v1/booking/slots?department_id={department}&limit=5", headers=auth
    ).json()
    assert offers, "a seeded department should have open seats"
    assert all(o["doctor_name"] and o["starts_at"] for o in offers)


def test_booking_then_cancelling_frees_the_seat(client, auth, department, a_patient):
    offers = client.get(
        f"/api/v1/booking/slots?department_id={department}&limit=1", headers=auth
    ).json()
    slot = offers[0]["slot_id"]

    r = client.post(
        "/api/v1/booking",
        headers=auth,
        json={"patient_id": a_patient, "slot_id": slot, "channel": Channel.WHATSAPP.value},
    )
    assert r.status_code == 201, r.text
    appt = r.json()
    assert appt["token_number"] is not None
    assert appt["noshow_prob"] is not None, "a booking should carry a no-show estimate"

    # booking that seat again must be refused, not silently double-booked
    again = client.post(
        "/api/v1/booking",
        headers=auth,
        json={"patient_id": a_patient, "slot_id": slot, "channel": "PWA"},
    )
    assert again.status_code == 409

    cancelled = client.post(f"/api/v1/booking/{appt['appointment_id']}/cancel", headers=auth).json()
    assert cancelled["status"] == "CANCELLED"

    freed = client.get(
        f"/api/v1/booking/slots?department_id={department}&limit=50", headers=auth
    ).json()
    assert any(o["slot_id"] == slot for o in freed), "cancelling should give the seat back"


def test_booking_notifies_the_patient(client, auth, department, a_patient):
    offers = client.get(
        f"/api/v1/booking/slots?department_id={department}&limit=3", headers=auth
    ).json()
    r = client.post(
        "/api/v1/booking",
        headers=auth,
        json={"patient_id": a_patient, "slot_id": offers[-1]["slot_id"], "channel": "SMS"},
    )
    assert r.status_code == 201

    # Look for THIS booking's message rather than counting rows: the outbox is capped
    # at 500 per page, so once a long-lived database passes that, a count can never
    # grow and the test silently stops testing anything.
    newest = client.get("/api/v1/notifications?limit=5", headers=auth).json()
    assert any(
        n["template"] == "booked" for n in newest
    ), "a booking the patient is never told about is not a booking"


def test_rescheduling_keeps_the_chain(client, auth, department, a_patient):
    offers = client.get(
        f"/api/v1/booking/slots?department_id={department}&limit=6", headers=auth
    ).json()
    first = client.post(
        "/api/v1/booking",
        headers=auth,
        json={"patient_id": a_patient, "slot_id": offers[0]["slot_id"], "channel": "PWA"},
    ).json()

    moved = client.post(
        f"/api/v1/booking/{first['appointment_id']}/reschedule",
        headers=auth,
        json={"to_slot_id": offers[-1]["slot_id"]},
    )
    assert moved.status_code == 200, moved.text
    assert moved.json()["appointment_id"] != first["appointment_id"]

    history = client.get(f"/api/v1/booking/patient/{a_patient}", headers=auth).json()
    assert any(a["status"] == "RESCHEDULED" for a in history), "the old row should survive"


def test_cancelling_twice_is_refused_not_silently_repeated(client, auth, department, a_patient):
    offers = client.get(
        f"/api/v1/booking/slots?department_id={department}&limit=2", headers=auth
    ).json()
    appt = client.post(
        "/api/v1/booking",
        headers=auth,
        json={"patient_id": a_patient, "slot_id": offers[0]["slot_id"], "channel": "PWA"},
    ).json()
    assert (
        client.post(f"/api/v1/booking/{appt['appointment_id']}/cancel", headers=auth).status_code
        == 200
    )
    second = client.post(f"/api/v1/booking/{appt['appointment_id']}/cancel", headers=auth)
    assert second.status_code == 409


def test_booking_requires_auth(client):
    assert client.get("/api/v1/booking/slots?department_id=" + "0" * 8).status_code in (401, 422)

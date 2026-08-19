"""Delete semantics are judge-facing: the outbox and the presence evidence trail are
the proof behind M1/M2/M3 accept scenarios, so deleting a parent must not erase them."""

import os
import uuid

import pytest
from sqlalchemy import NullPool, text
from sqlalchemy.ext.asyncio import create_async_engine


async def scalar(db, sql: str, **params):
    return (await db.execute(text(sql), params)).scalar()


@pytest.fixture
async def db():
    """Own engine, unpooled: asyncpg connections are bound to the event loop that
    opened them, and the session-scoped TestClient runs the app on a different one."""
    engine = create_async_engine(os.environ["DATABASE_URL"], poolclass=NullPool)
    async with engine.connect() as conn:
        yield conn
        await conn.rollback()  # each test leaves the seeded data as it found it
    await engine.dispose()


async def test_deleting_an_appointment_keeps_its_notification(db):
    patient = await scalar(db, "select id from patients limit 1")
    hospital = await scalar(db, "select id from hospitals limit 1")
    department = await scalar(
        db, "select id from departments where hospital_id=:h limit 1", h=hospital
    )
    doctor = await scalar(db, "select id from doctors where department_id=:d limit 1", d=department)

    slot = await scalar(
        db,
        "insert into slots (doctor_id, department_id, starts_at, ends_at, capacity, status)"
        " values (:doc, :dep, now(), now() + interval '10 min', 1, 'OPEN') returning id",
        doc=doctor,
        dep=department,
    )
    appt = await scalar(
        db,
        "insert into appointments (patient_id, slot_id, hospital_id, department_id, channel,"
        " priority_class, status) values (:p, :s, :h, :d, 'SMS', 'GENERAL', 'BOOKED') returning id",
        p=patient,
        s=slot,
        h=hospital,
        d=department,
    )
    note = await scalar(
        db,
        "insert into notifications (appointment_id, patient_id, channel, template, payload,"
        " mock, status) values (:a, :p, 'SMS', 'booked', '{}', true, 'SENT') returning id",
        a=appt,
        p=patient,
    )

    await db.execute(text("delete from appointments where id = :a"), {"a": appt})

    kept = await scalar(db, "select appointment_id from notifications where id = :n", n=note)
    assert kept is None, "appointment_id should be cleared, not cascade-delete the outbox row"
    assert await scalar(db, "select count(*) from notifications where id = :n", n=note) == 1


async def test_a_booked_slot_cannot_be_deleted(db):
    """RESTRICT: a Phase 1B replan must move appointments, never delete slots under them."""
    department = await scalar(db, "select id from departments limit 1")
    doctor = await scalar(db, "select id from doctors where department_id=:d limit 1", d=department)
    patient = await scalar(db, "select id from patients limit 1")
    hospital = await scalar(db, "select hospital_id from departments where id=:d", d=department)

    slot = await scalar(
        db,
        "insert into slots (doctor_id, department_id, starts_at, ends_at, capacity, status)"
        " values (:doc, :dep, now(), now() + interval '10 min', 1, 'OPEN') returning id",
        doc=doctor,
        dep=department,
    )
    await db.execute(
        text(
            "insert into appointments (patient_id, slot_id, hospital_id, department_id, channel,"
            " priority_class, status) values (:p, :s, :h, :d, 'PWA', 'GENERAL', 'BOOKED')"
        ),
        {"p": patient, "s": slot, "h": hospital, "d": department},
    )

    with pytest.raises(Exception, match="violates foreign key constraint"):
        await db.execute(text("delete from slots where id = :s"), {"s": slot})


async def test_presence_evidence_survives_a_zone_being_removed(db):
    """M1's accept criteria rest on the evidence trail; remapping a beacon must not erase it."""
    doctor = await scalar(db, "select id from doctors limit 1")
    hospital = await scalar(db, "select hospital_id from doctors where id=:d", d=doctor)

    zone = await scalar(
        db,
        "insert into zones (hospital_id, name, kind) values (:h, :n, 'GATE') returning id",
        h=hospital,
        n=f"probe-{uuid.uuid4().hex[:8]}",
    )
    signal = await scalar(
        db,
        "insert into presence_signals (doctor_id, source, zone_id, raw, observed_at, trust)"
        " values (:doc, 'BLE', :z, '{}', now(), 0.7) returning id",
        doc=doctor,
        z=zone,
    )

    await db.execute(text("delete from zones where id = :z"), {"z": zone})

    assert await scalar(db, "select count(*) from presence_signals where id = :s", s=signal) == 1

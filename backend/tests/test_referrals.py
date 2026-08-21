"""M5: a hold that releases itself, and never resurrects.

Driven through `client.portal.call` rather than `@pytest.mark.asyncio`, following
test_otp.py: the engine's pool is bound to the app's own event loop, and a fresh loop
per test hands you "attached to a different loop" from asyncpg.

These build their own beds rather than leaning on `seed_facilities`, because the suite
shares one database and a test that consumes the last free ICU bed would break whatever
ran next (CLAUDE.md §Conventions).
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, select

from app.db import SessionLocal
from app.models import (
    Bed,
    BedAllocation,
    BedKind,
    BedState,
    Hospital,
    Patient,
    Referral,
    ReferralStatus,
    ReferralUrgency,
    Slot,
    SlotStatus,
)
from app.services import referrals


async def _two_hospitals(db) -> tuple[Hospital, Hospital]:
    rows = (await db.execute(select(Hospital).limit(2))).scalars().all()
    assert len(rows) == 2, "run `make seed` first"
    return rows[0], rows[1]


async def _bed(db, hospital_id, kind=BedKind.ICU) -> Bed:
    """A bed this test owns outright, so it cannot starve another test of a real one.

    The ward is prefixed "AAA" so it sorts ahead of every seeded ward: reserve() orders
    by (ward, code), so this is the bed the test deterministically gets.
    """
    # Clear any bed a crashed earlier run left behind: two "AAA-Test-*" wards sort
    # against each other by random hex, so a stray one would win the ordering and this
    # test would reserve a bed it does not own.
    await db.execute(
        delete(BedAllocation).where(
            BedAllocation.bed_id.in_(select(Bed.id).where(Bed.ward.like("AAA-Test%")))
        )
    )
    await db.execute(delete(Bed).where(Bed.ward.like("AAA-Test%")))
    bed = Bed(
        hospital_id=hospital_id,
        ward=f"AAA-Test-{uuid.uuid4().hex[:6]}",
        code=uuid.uuid4().hex[:8].upper(),
        kind=kind,
        state=BedState.FREE,
    )
    db.add(bed)
    await db.flush()
    return bed


async def _patient(db) -> Patient:
    return (await db.execute(select(Patient).limit(1))).scalars().one()


def test_request_holds_a_bed_and_sets_an_expiry(client):
    async def go():
        async with SessionLocal() as db:
            src, dst = await _two_hospitals(db)
            bed = await _bed(db, dst.id)
            patient = await _patient(db)

            referral = await referrals.request(
                db,
                from_hospital_id=src.id,
                to_hospital_id=dst.id,
                patient_id=patient.id,
                specialty="Trauma",  # maps to ICU
                urgency=ReferralUrgency.EMERGENCY,
            )
            out = (referral.status, referral.reserved_bed_id == bed.id, referral.expires_at)
            await db.refresh(bed)
            state = bed.state
            await db.rollback()
            return (*out, state)

    status, took_our_bed, expires_at, bed_state = client.portal.call(go)
    assert status is ReferralStatus.RESERVED
    assert took_our_bed
    assert expires_at is not None
    assert bed_state is BedState.RESERVED


def test_expiry_releases_the_bed_and_the_slot_together(client):
    """The acceptance criterion: "expiry releases it automatically"."""

    async def setup():
        async with SessionLocal() as db:
            src, dst = await _two_hospitals(db)
            bed = await _bed(db, dst.id)
            patient = await _patient(db)
            slot = (
                (await db.execute(select(Slot).where(Slot.status == SlotStatus.OPEN).limit(1)))
                .scalars()
                .one()
            )

            referral = await referrals.request(
                db,
                from_hospital_id=src.id,
                to_hospital_id=dst.id,
                patient_id=patient.id,
                specialty="Trauma",
                urgency=ReferralUrgency.EMERGENCY,
            )
            # A specialist slot held alongside the bed. Releasing one and forgetting the
            # other leaves a consultant's calendar blocked for a patient not coming.
            referral.reserved_slot_id = slot.id
            slot.status = SlotStatus.BLOCKED
            referral.expires_at = datetime.now(UTC) - timedelta(minutes=1)
            ids = (referral.id, bed.id, slot.id)
            await db.commit()
            return ids

    referral_id, bed_id, slot_id = client.portal.call(setup)

    released = client.portal.call(referrals.expire_due)
    assert released >= 1

    async def check():
        async with SessionLocal() as db:
            after = (
                (await db.execute(select(Referral).where(Referral.id == referral_id)))
                .scalars()
                .one()
            )
            return (
                after.status,
                after.reserved_bed_id,
                after.reserved_slot_id,
                (await db.execute(select(Bed.state).where(Bed.id == bed_id))).scalar_one(),
                (await db.execute(select(Slot.status).where(Slot.id == slot_id))).scalar_one(),
            )

    status, bed_ref, slot_ref, bed_state, slot_status = client.portal.call(check)
    assert status is ReferralStatus.EXPIRED
    assert bed_ref is None and slot_ref is None
    assert bed_state is BedState.FREE
    assert slot_status is SlotStatus.OPEN


def test_confirming_a_just_expired_hold_does_not_resurrect_it(client):
    """The bed is already back in the pool and may already belong to someone else.
    Confirming would be claiming a bed we do not have."""

    async def go():
        async with SessionLocal() as db:
            src, dst = await _two_hospitals(db)
            await _bed(db, dst.id)
            patient = await _patient(db)

            referral = await referrals.request(
                db,
                from_hospital_id=src.id,
                to_hospital_id=dst.id,
                patient_id=patient.id,
                specialty="Trauma",
                urgency=ReferralUrgency.EMERGENCY,
            )
            bed_id = referral.reserved_bed_id
            # Expired one second ago, before any sweeper had a chance to run.
            referral.expires_at = datetime.now(UTC) - timedelta(seconds=1)
            await db.flush()

            raised = False
            try:
                await referrals.confirm(db, referral.id)
            except referrals.ReferralError as exc:
                raised = "expired" in str(exc)

            state = (await db.execute(select(Bed.state).where(Bed.id == bed_id))).scalar_one()
            status = referral.status
            await db.rollback()
            return raised, status, state

    raised, status, bed_state = client.portal.call(go)
    assert raised, "confirming an expired hold must fail, not resurrect it"
    assert status is ReferralStatus.EXPIRED
    assert bed_state is BedState.FREE


def test_no_free_bed_leaves_the_referral_visible_rather_than_failing(client):
    """The receiving hospital should see that someone is trying to send them a patient
    even when they have nowhere to put them. That is a conversation, not a 409."""

    async def go():
        async with SessionLocal() as db:
            src, dst = await _two_hospitals(db)
            patient = await _patient(db)
            # Take every ICU bed at the destination out of the pool, in this
            # transaction only — the rollback at the end puts them all back.
            for bed in (
                (
                    await db.execute(
                        select(Bed).where(Bed.hospital_id == dst.id, Bed.kind == BedKind.ICU)
                    )
                )
                .scalars()
                .all()
            ):
                bed.state = BedState.OCCUPIED
            await db.flush()

            referral = await referrals.request(
                db,
                from_hospital_id=src.id,
                to_hospital_id=dst.id,
                patient_id=patient.id,
                specialty="Trauma",
                urgency=ReferralUrgency.EMERGENCY,
            )
            out = (referral.status, referral.reserved_bed_id)
            await db.rollback()
            return out

    status, bed_id = client.portal.call(go)
    assert status is ReferralStatus.REQUESTED
    assert bed_id is None


def test_cancel_gives_the_bed_back(client):
    async def go():
        async with SessionLocal() as db:
            src, dst = await _two_hospitals(db)
            await _bed(db, dst.id)
            patient = await _patient(db)

            referral = await referrals.request(
                db,
                from_hospital_id=src.id,
                to_hospital_id=dst.id,
                patient_id=patient.id,
                specialty="Trauma",
                urgency=ReferralUrgency.URGENT,
            )
            bed_id = referral.reserved_bed_id
            await referrals.cancel(db, referral.id)
            state = (await db.execute(select(Bed.state).where(Bed.id == bed_id))).scalar_one()
            status = referral.status
            await db.rollback()
            return status, state

    status, bed_state = client.portal.call(go)
    assert status is ReferralStatus.CANCELLED
    assert bed_state is BedState.FREE


def test_a_hospital_cannot_refer_to_itself(client):
    async def go():
        async with SessionLocal() as db:
            src, _ = await _two_hospitals(db)
            patient = await _patient(db)
            try:
                await referrals.request(
                    db,
                    from_hospital_id=src.id,
                    to_hospital_id=src.id,
                    patient_id=patient.id,
                    specialty="Trauma",
                    urgency=ReferralUrgency.ROUTINE,
                )
                return False
            except referrals.ReferralError:
                return True
            finally:
                await db.rollback()

    assert client.portal.call(go)


@pytest.mark.parametrize(
    "specialty,expected",
    [
        ("Trauma", BedKind.ICU),
        ("Obstetrics & Gynaecology", BedKind.MATERNITY),
        ("Something Unmapped", BedKind.GENERAL),
    ],
)
def test_specialty_decides_the_ward(specialty, expected):
    """A wrong guess here puts a trauma case in a maternity bed."""
    assert referrals.KIND_FOR_SPECIALTY.get(specialty, BedKind.GENERAL) is expected


def test_a_held_bed_cannot_be_taken_by_hand(client, admin_token):
    """Blocking the way in is not enough. Taking a held bed by hand would leave the
    referring hospital believing it still has a bed at the destination."""
    headers = {"Authorization": f"Bearer {admin_token}"}

    async def setup():
        async with SessionLocal() as db:
            src, dst = await _two_hospitals(db)
            await _bed(db, dst.id)
            patient = await _patient(db)
            referral = await referrals.request(
                db,
                from_hospital_id=src.id,
                to_hospital_id=dst.id,
                patient_id=patient.id,
                specialty="Trauma",
                urgency=ReferralUrgency.EMERGENCY,
            )
            ids = (str(referral.reserved_bed_id), str(referral.id))
            await db.commit()
            return ids

    bed_id, referral_id = client.portal.call(setup)
    try:
        r = client.post(f"/api/v1/beds/{bed_id}/state", json={"state": "OCCUPIED"}, headers=headers)
        assert r.status_code == 409, r.text
        assert referral_id in r.json()["detail"]

        # And reserving by hand stays refused from the other direction.
        r = client.post(f"/api/v1/beds/{bed_id}/state", json={"state": "RESERVED"}, headers=headers)
        assert r.status_code == 409

        # Cancelling the referral is the way out, and then the bed moves.
        assert (
            client.post(f"/api/v1/referrals/{referral_id}/cancel", headers=headers).status_code
            == 200
        )
        r = client.post(f"/api/v1/beds/{bed_id}/state", json={"state": "CLEANING"}, headers=headers)
        assert r.status_code == 200, r.text
        assert r.json()["state"] == "CLEANING"
    finally:
        # This test commits, so it cleans up after itself rather than leaving a stray
        # bed and referral behind for whatever runs next.
        async def cleanup():
            async with SessionLocal() as db:
                await db.execute(delete(Referral).where(Referral.id == uuid.UUID(referral_id)))
                await db.execute(
                    delete(BedAllocation).where(BedAllocation.bed_id == uuid.UUID(bed_id))
                )
                await db.execute(delete(Bed).where(Bed.id == uuid.UUID(bed_id)))
                await db.commit()

        client.portal.call(cleanup)

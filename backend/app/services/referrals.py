"""Referral reservation with expiry — PRD §M5.

Facility A holds a bed (and optionally a specialist slot) at facility B, B sees it held,
and **the hold expires by itself**. That last part is the whole point: a reservation that
only releases when someone remembers to click cancel is how a district hospital ends up
believing an ICU bed exists in Shimla that was given away three hours ago.

Status flow: REQUESTED → RESERVED → CONFIRMED → ARRIVED, with EXPIRED and CANCELLED as
the two ways out. Only RESERVED holds anything, so only RESERVED has anything to release.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import events
from app.db import SessionLocal
from app.models import (
    Bed,
    BedKind,
    Referral,
    ReferralStatus,
    ReferralUrgency,
    Slot,
    SlotStatus,
)
from app.services import beds

log = logging.getLogger("swasthya.referrals")

# How long a hold survives unconfirmed, by urgency. An emergency transfer is either
# under way within the hour or it is not happening; a routine one can wait a day.
HOLD_FOR = {
    ReferralUrgency.EMERGENCY: timedelta(hours=2),
    ReferralUrgency.URGENT: timedelta(hours=6),
    ReferralUrgency.ROUTINE: timedelta(hours=24),
}

# Which ward a referral lands in. Kept deliberately small and explicit rather than
# inferred from free text — a wrong guess here puts a trauma case in a maternity bed.
KIND_FOR_SPECIALTY = {
    "Trauma": BedKind.ICU,
    "Neurosurgery": BedKind.ICU,
    "Cardiology": BedKind.ICU,
    "General Surgery": BedKind.GENERAL,
    "General Medicine": BedKind.GENERAL,
    "Orthopaedics": BedKind.GENERAL,
    "Obstetrics & Gynaecology": BedKind.MATERNITY,
    "Paediatrics": BedKind.GENERAL,
}


class ReferralError(Exception):
    """The referral could not be placed or moved. Never silently downgraded."""


async def request(
    db: AsyncSession,
    *,
    from_hospital_id: uuid.UUID,
    to_hospital_id: uuid.UUID,
    patient_id: uuid.UUID,
    specialty: str,
    urgency: ReferralUrgency,
    notes: str | None = None,
    now: datetime | None = None,
) -> Referral:
    """Create the referral and hold a bed at the destination in one act.

    If no bed can be held the referral still exists, as REQUESTED — the receiving
    hospital should see that someone is trying to send them a patient even when they
    have nowhere to put them. That is a conversation, not a 409.
    """
    now = now or datetime.now(UTC)
    if from_hospital_id == to_hospital_id:
        raise ReferralError("a hospital cannot refer to itself")

    referral = Referral(
        from_hospital_id=from_hospital_id,
        to_hospital_id=to_hospital_id,
        patient_id=patient_id,
        specialty=specialty,
        urgency=urgency,
        status=ReferralStatus.REQUESTED,
        notes=notes,
    )
    db.add(referral)
    await db.flush()

    kind = KIND_FOR_SPECIALTY.get(specialty, BedKind.GENERAL)
    expires_at = now + HOLD_FOR[urgency]
    try:
        bed = await beds.reserve(
            db,
            hospital_id=to_hospital_id,
            kind=kind,
            patient_id=patient_id,
            referral_id=referral.id,
            until=expires_at,
        )
    except beds.BedError as exc:
        log.info("referral %s stays REQUESTED: %s", referral.id, exc)
        await db.flush()
        return referral

    referral.reserved_bed_id = bed.id
    referral.status = ReferralStatus.RESERVED
    referral.expires_at = expires_at
    await db.flush()
    await _publish(referral, "referral.reserved")
    return referral


async def confirm(
    db: AsyncSession, referral_id: uuid.UUID, now: datetime | None = None
) -> Referral:
    """The sending facility says the patient is on the way.

    An expired hold is NOT resurrected here. The bed is already back in the pool and may
    already belong to someone else; confirming would be claiming a bed we do not have.
    """
    now = now or datetime.now(UTC)
    referral = await _get(db, referral_id)
    if referral.status is ReferralStatus.EXPIRED:
        raise ReferralError("this reservation expired; place a new referral")
    if referral.status is not ReferralStatus.RESERVED:
        raise ReferralError(f"cannot confirm a referral that is {referral.status.value}")
    if referral.expires_at is not None and referral.expires_at <= now:
        # Expired a moment ago and the sweeper has not run yet. Expire it here rather
        # than letting a race hand out a bed that is about to be released anyway.
        await _expire(db, referral)
        raise ReferralError("this reservation expired; place a new referral")

    referral.status = ReferralStatus.CONFIRMED
    await db.flush()
    await _publish(referral, "referral.confirmed")
    return referral


async def cancel(db: AsyncSession, referral_id: uuid.UUID) -> Referral:
    """Give everything back. Valid from any state that still holds something."""
    referral = await _get(db, referral_id)
    if referral.status in (ReferralStatus.EXPIRED, ReferralStatus.CANCELLED):
        return referral
    await _release_holds(db, referral)
    referral.status = ReferralStatus.CANCELLED
    await db.flush()
    await _publish(referral, "referral.cancelled")
    return referral


async def expire_due(now: datetime | None = None) -> int:
    """Release every hold whose time is up. Returns how many expired.

    This is what makes "expiry releases it automatically" true. It runs on a timer, not
    on read, so a bed comes back into the destination's free count whether or not anyone
    is looking at a screen.
    """
    now = now or datetime.now(UTC)
    expired = 0
    async with SessionLocal() as db:
        due = (
            (
                await db.execute(
                    select(Referral).where(
                        Referral.status == ReferralStatus.RESERVED,
                        Referral.expires_at.is_not(None),
                        Referral.expires_at <= now,
                    )
                )
            )
            .scalars()
            .all()
        )
        for referral in due:
            await _expire(db, referral)
            expired += 1
        await db.commit()
    if expired:
        log.info("released %d expired referral hold(s)", expired)
    return expired


async def expire_forever(interval_seconds: int) -> None:
    while True:
        try:
            await asyncio.sleep(interval_seconds)
            await expire_due()
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("referral expiry sweep failed; continuing")


# --- internals ----------------------------------------------------------------


async def _get(db: AsyncSession, referral_id: uuid.UUID) -> Referral:
    referral = (
        await db.execute(select(Referral).where(Referral.id == referral_id))
    ).scalar_one_or_none()
    if referral is None:
        raise ReferralError("no such referral")
    return referral


async def _release_holds(db: AsyncSession, referral: Referral) -> None:
    """Both holds, always together. Releasing the bed and forgetting the slot leaves a
    specialist's calendar blocked for a patient who is not coming."""
    if referral.reserved_bed_id:
        await beds.release(db, referral.reserved_bed_id)
        referral.reserved_bed_id = None
    if referral.reserved_slot_id:
        slot = (
            await db.execute(select(Slot).where(Slot.id == referral.reserved_slot_id))
        ).scalar_one_or_none()
        if slot is not None:
            slot.status = SlotStatus.OPEN
        referral.reserved_slot_id = None


async def _expire(db: AsyncSession, referral: Referral) -> None:
    await _release_holds(db, referral)
    referral.status = ReferralStatus.EXPIRED
    await db.flush()
    await _publish(referral, "referral.expired")


async def _publish(referral: Referral, topic: str) -> None:
    await events.publish(
        topic,
        {
            "referral_id": str(referral.id),
            "to_hospital_id": str(referral.to_hospital_id),
            "status": referral.status.value,
            "specialty": referral.specialty,
        },
    )


async def bed_for(db: AsyncSession, referral: Referral) -> Bed | None:
    if not referral.reserved_bed_id:
        return None
    return (
        await db.execute(select(Bed).where(Bed.id == referral.reserved_bed_id))
    ).scalar_one_or_none()

"""What "the doctor is available" means when presence and the roster disagree.

This is the hinge between M1 and M2, so the rule lives in one place:

    The roster decides when slots *exist*. A confident presence state that
    contradicts the roster removes them. A low-confidence state changes nothing,
    because a low-confidence state *is* the roster — treating it as fact would
    re-introduce exactly the optimism the presence board exists to expose.

So forward booking still works (hospitals book against a roster months out), while
a doctor who is demonstrably absent stops absorbing patients.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Doctor, DoctorStatus, PresenceState, Slot, SlotStatus
from app.services.presence import FLIP_THRESHOLD

# How long a confident IN_SURGERY blocks the clinic list for. A theatre list is not
# a five-minute errand, and the doctor is not seeing OPD patients during it.
SURGERY_BLOCK = timedelta(hours=2)


@dataclass(frozen=True)
class Unavailability:
    """Why a doctor cannot see patients, and for how long."""

    doctor_id: uuid.UUID
    state: PresenceState
    confidence: float
    reason: str
    until: datetime | None  # None = for the rest of the day


def is_confident(status: DoctorStatus | None) -> bool:
    """A state we actually observed, as opposed to one the roster implied."""
    if status is None:
        return False
    if (status.evidence or {}).get("degraded_to_roster"):
        return False
    return float(status.confidence) >= FLIP_THRESHOLD


def unavailability_for(
    status: DoctorStatus | None, now: datetime | None = None
) -> Unavailability | None:
    """None means bookable. Only a *confident* contradiction takes slots away."""
    now = now or datetime.now(UTC)
    if not is_confident(status):
        return None

    blocking = {
        PresenceState.ON_LEAVE: ("on leave", None),
        PresenceState.OFF_SHIFT: ("off shift", None),
        PresenceState.IN_SURGERY: ("in theatre", now + SURGERY_BLOCK),
    }
    if status.state not in blocking:
        return None

    reason, until = blocking[status.state]
    manual = (status.evidence or {}).get("manual_override")
    return Unavailability(
        doctor_id=status.doctor_id,
        state=status.state,
        confidence=float(status.confidence),
        reason=f"{reason} (set by an administrator)" if manual else reason,
        until=until,
    )


async def unavailable_doctors(
    db: AsyncSession, hospital_id: uuid.UUID | None = None, now: datetime | None = None
) -> dict[uuid.UUID, Unavailability]:
    q = select(DoctorStatus).join(Doctor, Doctor.id == DoctorStatus.doctor_id)
    if hospital_id:
        q = q.where(Doctor.hospital_id == hospital_id)
    rows = (await db.execute(q)).scalars().all()
    out = {}
    for status in rows:
        blocked = unavailability_for(status, now)
        if blocked:
            out[status.doctor_id] = blocked
    return out


async def bookable_slots(
    db: AsyncSession,
    department_id: uuid.UUID,
    frm: datetime,
    until: datetime,
    *,
    exclude_doctor: uuid.UUID | None = None,
    now: datetime | None = None,
) -> list[Slot]:
    """Open slots in a department that a confidently-absent doctor is not holding."""
    now = now or datetime.now(UTC)
    slots = (
        (
            await db.execute(
                select(Slot)
                .where(
                    Slot.department_id == department_id,
                    Slot.starts_at >= frm,
                    Slot.starts_at <= until,
                    Slot.status == SlotStatus.OPEN,
                )
                .order_by(Slot.starts_at)
            )
        )
        .scalars()
        .all()
    )
    blocked = await unavailable_doctors(db, now=now)
    keep = []
    for slot in slots:
        if exclude_doctor and slot.doctor_id == exclude_doctor:
            continue
        gone = blocked.get(slot.doctor_id)
        if gone and (gone.until is None or slot.starts_at < gone.until):
            continue
        keep.append(slot)
    return keep

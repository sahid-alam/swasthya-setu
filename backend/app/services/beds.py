"""Bed inventory and occupancy — PRD §M5.

States are the §9d vocabulary: FREE, OCCUPIED, RESERVED, CLEANING, OOO. A bed leaves
FREE only through this module, so "who took it and until when" has exactly one answer.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Bed, BedAllocation, BedKind, BedState, Hospital


class BedError(Exception):
    """No bed could be taken. Callers surface this; they never invent a bed."""


@dataclass(frozen=True)
class WardOccupancy:
    hospital_id: str
    hospital: str
    ward: str
    kind: BedKind
    free: int
    occupied: int
    reserved: int
    cleaning: int
    ooo: int

    @property
    def total(self) -> int:
        return self.free + self.occupied + self.reserved + self.cleaning + self.ooo


async def occupancy(db: AsyncSession, hospital_id: uuid.UUID | None = None) -> list[WardOccupancy]:
    """One row per ward, counted by state. The command centre's whole bed picture."""
    q = (
        select(Hospital.id, Hospital.name, Bed.ward, Bed.kind, Bed.state, func.count(Bed.id))
        .join(Hospital, Hospital.id == Bed.hospital_id)
        .group_by(Hospital.id, Hospital.name, Bed.ward, Bed.kind, Bed.state)
    )
    if hospital_id:
        q = q.where(Bed.hospital_id == hospital_id)

    buckets: dict[tuple, dict[BedState, int]] = {}
    for hid, hname, ward, kind, state, count in (await db.execute(q)).all():
        buckets.setdefault((str(hid), hname, ward, kind), {})[state] = count

    return sorted(
        (
            WardOccupancy(
                hospital_id=hid,
                hospital=hname,
                ward=ward,
                kind=kind,
                free=states.get(BedState.FREE, 0),
                occupied=states.get(BedState.OCCUPIED, 0),
                reserved=states.get(BedState.RESERVED, 0),
                cleaning=states.get(BedState.CLEANING, 0),
                ooo=states.get(BedState.OOO, 0),
            )
            for (hid, hname, ward, kind), states in buckets.items()
        ),
        key=lambda w: (w.hospital, w.ward),
    )


async def free_count(db: AsyncSession, hospital_id: uuid.UUID, kind: BedKind | None = None) -> int:
    """How many beds this hospital could actually give someone right now.

    The Golden Hour ranking reads this, so it counts FREE only — a bed that is CLEANING
    will probably be free in an hour, and "probably, in an hour" is not a thing to route
    a trauma case on.
    """
    q = select(func.count(Bed.id)).where(Bed.hospital_id == hospital_id, Bed.state == BedState.FREE)
    if kind:
        q = q.where(Bed.kind == kind)
    return (await db.execute(q)).scalar_one()


async def reserve(
    db: AsyncSession,
    *,
    hospital_id: uuid.UUID,
    kind: BedKind,
    patient_id: uuid.UUID | None = None,
    referral_id: uuid.UUID | None = None,
    until: datetime | None = None,
) -> Bed:
    """Take one FREE bed of `kind` and hold it.

    `FOR UPDATE SKIP LOCKED` so two referrals racing for the last ICU bed cannot both
    win: the loser skips the locked row and either finds another or is told there is
    none, which is the honest answer.
    """
    bed = (
        await db.execute(
            select(Bed)
            .where(
                Bed.hospital_id == hospital_id,
                Bed.kind == kind,
                Bed.state == BedState.FREE,
            )
            .order_by(Bed.ward, Bed.code)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
    ).scalar_one_or_none()
    if bed is None:
        raise BedError(f"no free {kind.value} bed at this hospital")

    bed.state = BedState.RESERVED
    db.add(
        BedAllocation(
            bed_id=bed.id,
            patient_id=patient_id,
            referral_id=referral_id,
            # The database clock, always — mixing a Python clock in on one branch
            # made an allocation's start time depend on whether an expiry was given.
            from_at=func.now(),
            to_at=until,
        )
    )
    await db.flush()
    return bed


async def release(db: AsyncSession, bed_id: uuid.UUID, *, to: BedState = BedState.FREE) -> None:
    """Give a held bed back. Idempotent: releasing a FREE bed is not an error, because
    the expiry sweeper and a human clicking cancel can race and both are right."""
    bed = (await db.execute(select(Bed).where(Bed.id == bed_id))).scalar_one_or_none()
    if bed is None or bed.state == to:
        return
    bed.state = to
    allocation = (
        await db.execute(
            select(BedAllocation)
            .where(BedAllocation.bed_id == bed_id, BedAllocation.to_at.is_(None))
            .order_by(BedAllocation.from_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if allocation is not None:
        allocation.to_at = func.now()
    await db.flush()

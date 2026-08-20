"""Command-centre alerts — PRD §M4.

Computed on read rather than stored. An alert is a *current* statement about the
world ("this doctor is rostered but not here"), and a stored one goes stale the
moment the world moves — which is the failure mode this whole system exists to fix.
`alert.raised` remains the pub/sub topic for pushing them; this is the read model.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Appointment,
    AppointmentStatus,
    Department,
    Doctor,
    DoctorStatus,
    Hospital,
    PresenceState,
    Shift,
    ShiftKind,
    Slot,
    User,
)
from app.services.availability import is_confident

# A queue this far past its scheduled time is not "running late", it is overflowing.
QUEUE_OVERFLOW_MINUTES = 45
# How long into a shift a doctor can stay unaccounted for before it is worth saying.
MISSING_GRACE_MINUTES = 20


@dataclass
class Alert:
    kind: str
    severity: str  # info | warn | critical  (DESIGN.md §9d)
    title: str
    detail: str
    hospital: str
    department: str | None = None
    doctor_id: str | None = None
    department_id: str | None = None


async def roster_vs_presence(db: AsyncSession, now: datetime) -> list[Alert]:
    """The alert this product is named for: the roster says one thing, the building
    says another. Only fires on a *confident* contradiction — a low-confidence guess
    is the roster, so alerting on it would be the system arguing with itself."""
    rows = (
        await db.execute(
            select(Doctor, User, Department, Hospital, DoctorStatus, Shift)
            .join(User, User.id == Doctor.user_id)
            .join(Department, Department.id == Doctor.department_id)
            .join(Hospital, Hospital.id == Doctor.hospital_id)
            .outerjoin(DoctorStatus, DoctorStatus.doctor_id == Doctor.id)
            .join(
                Shift,
                (Shift.doctor_id == Doctor.id) & (Shift.starts_at <= now) & (Shift.ends_at >= now),
            )
            .where(Shift.kind == ShiftKind.OPD)
        )
    ).all()

    out: list[Alert] = []
    for doctor, user, dept, hosp, status, shift in rows:
        booked = (
            await db.execute(
                select(func.count(Appointment.id))
                .join(Slot, Slot.id == Appointment.slot_id)
                .where(
                    Slot.doctor_id == doctor.id,
                    Slot.starts_at >= now,
                    Appointment.status == AppointmentStatus.BOOKED,
                )
            )
        ).scalar_one()

        if (
            status is not None
            and is_confident(status)
            and status.state
            in (
                PresenceState.ON_LEAVE,
                PresenceState.OFF_SHIFT,
            )
        ):
            out.append(
                Alert(
                    kind="roster_mismatch",
                    severity="critical" if booked else "warn",
                    title=f"{user.name} is rostered but absent",
                    detail=(
                        f"Roster says OPD until {shift.ends_at:%H:%M}; presence says "
                        f"{status.state.value.replace('_', ' ').lower()} "
                        f"({float(status.confidence):.0%} confidence). "
                        + (f"{booked} patients still booked." if booked else "No patients booked.")
                    ),
                    hospital=hosp.name,
                    department=dept.name,
                    doctor_id=str(doctor.id),
                    department_id=str(dept.id),
                )
            )
            continue

        # Rostered, shift well underway, and nothing has ever seen them.
        started_ago = (now - shift.starts_at).total_seconds() / 60
        unseen = status is None or status.state == PresenceState.UNKNOWN
        if unseen and started_ago > MISSING_GRACE_MINUTES:
            out.append(
                Alert(
                    kind="unaccounted",
                    severity="warn" if booked else "info",
                    title=f"{user.name} has not been seen",
                    detail=(
                        f"Shift started {int(started_ago)} min ago and no signal has "
                        f"arrived. {booked} patients booked."
                    ),
                    hospital=hosp.name,
                    department=dept.name,
                    doctor_id=str(doctor.id),
                    department_id=str(dept.id),
                )
            )
    return out


async def queue_overflow(db: AsyncSession, now: datetime) -> list[Alert]:
    """Departments where the oldest waiting patient is far past their slot time."""
    rows = (
        await db.execute(
            select(
                Department,
                Hospital,
                func.min(Slot.starts_at),
                func.count(Appointment.id),
            )
            .join(Hospital, Hospital.id == Department.hospital_id)
            .join(Appointment, Appointment.department_id == Department.id)
            .join(Slot, Slot.id == Appointment.slot_id)
            .where(
                Appointment.status == AppointmentStatus.BOOKED,
                Slot.starts_at <= now,
            )
            .group_by(Department.id, Hospital.id)
        )
    ).all()

    out = []
    for dept, hosp, oldest, waiting in rows:
        late = (now - oldest).total_seconds() / 60
        if late < QUEUE_OVERFLOW_MINUTES:
            continue
        out.append(
            Alert(
                kind="queue_overflow",
                severity="critical" if late > 2 * QUEUE_OVERFLOW_MINUTES else "warn",
                title=f"{dept.name} queue is {int(late)} min behind",
                detail=f"{waiting} patients waiting past their appointment time.",
                hospital=hosp.name,
                department=dept.name,
                department_id=str(dept.id),
            )
        )
    return out


async def pending_rebooking(db: AsyncSession) -> list[Alert]:
    """Patients a replan could not seat. They are owed an appointment and somebody
    has to actually ring them, so this belongs on the board, not in a report."""
    rows = (
        await db.execute(
            select(Department, Hospital, func.count(Appointment.id))
            .join(Hospital, Hospital.id == Department.hospital_id)
            .join(Appointment, Appointment.department_id == Department.id)
            .where(Appointment.status == AppointmentStatus.RESCHEDULE_PENDING)
            .group_by(Department.id, Hospital.id)
        )
    ).all()
    return [
        Alert(
            kind="reschedule_pending",
            severity="critical",
            title=f"{count} patients need rebooking by hand",
            detail=f"No slot could be found for them in {dept.name}. Call them.",
            hospital=hosp.name,
            department=dept.name,
            department_id=str(dept.id),
        )
        for dept, hosp, count in rows
        if count
    ]


SEVERITY_ORDER = {"critical": 0, "warn": 1, "info": 2}


async def current(
    db: AsyncSession, hospital_id: uuid.UUID | None = None, now: datetime | None = None
) -> list[Alert]:
    now = now or datetime.now(UTC)
    alerts = (
        await roster_vs_presence(db, now)
        + await queue_overflow(db, now)
        + await pending_rebooking(db)
    )
    if hospital_id:
        names = {
            h.name
            for h in (
                await db.execute(select(Hospital).where(Hospital.id == hospital_id))
            ).scalars()
        }
        alerts = [a for a in alerts if a.hospital in names]
    return sorted(alerts, key=lambda a: (SEVERITY_ORDER[a.severity], a.title))


async def network(db: AsyncSession, now: datetime | None = None) -> list[dict]:
    """Facility rows for the Leaflet map: where each hospital is and how it is doing."""
    now = now or datetime.now(UTC)
    hospitals = (await db.execute(select(Hospital))).scalars().all()
    alerts = await current(db, now=now)

    out = []
    for hosp in hospitals:
        states = (
            await db.execute(
                select(DoctorStatus.state, func.count(DoctorStatus.id))
                .join(Doctor, Doctor.id == DoctorStatus.doctor_id)
                .where(Doctor.hospital_id == hosp.id)
                .group_by(DoctorStatus.state)
            )
        ).all()
        waiting = (
            await db.execute(
                select(func.count(Appointment.id))
                .join(Slot, Slot.id == Appointment.slot_id)
                .where(
                    Appointment.hospital_id == hosp.id,
                    Appointment.status == AppointmentStatus.BOOKED,
                    Slot.starts_at >= now,
                )
            )
        ).scalar_one()
        mine = [a for a in alerts if a.hospital == hosp.name]
        out.append(
            {
                "hospital_id": str(hosp.id),
                "name": hosp.name,
                "code": hosp.code,
                "district": hosp.district,
                "level": hosp.level.value,
                "lat": float(hosp.lat),
                "lng": float(hosp.lng),
                "present": sum(
                    n
                    for s, n in states
                    if s
                    in (
                        PresenceState.PRESENT_IN_DEPT,
                        PresenceState.PRESENT_ELSEWHERE,
                        PresenceState.ON_ROUNDS,
                        PresenceState.IN_SURGERY,
                    )
                ),
                "doctors": sum(n for _, n in states),
                "waiting": waiting,
                "alerts": len(mine),
                "worst_severity": min(
                    (a.severity for a in mine), key=lambda s: SEVERITY_ORDER[s], default=None
                ),
            }
        )
    return out

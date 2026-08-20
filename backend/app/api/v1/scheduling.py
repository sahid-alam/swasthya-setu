"""Appointment allocation API — PRD §M2.

`plan_runs` is exposed read-only because it is the evidence for the "<5s" claim:
every solve records its status, objective, duration and how many patients moved.
"""

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import (
    Appointment,
    AppointmentStatus,
    Doctor,
    Patient,
    PlanRun,
    PlanTrigger,
    PriorityClass,
    Slot,
    User,
    UserRole,
)
from app.security import require_roles
from app.services import scheduling
from app.services.availability import unavailability_for

router = APIRouter(tags=["scheduling"])

STAFF = require_roles(UserRole.ADMIN, UserRole.STAFF)
ADMIN = require_roles(UserRole.ADMIN)


class MoveOut(BaseModel):
    appointment_id: str
    patient_name: str
    from_time: datetime
    to_time: datetime | None
    to_doctor: str | None
    displacement_minutes: int
    priority: PriorityClass


class PlanOut(BaseModel):
    solver_status: str
    objective: float | None
    duration_ms: int
    considered_slots: int
    moved: int
    unplaced: int
    moves: list[MoveOut]
    could_not_place: list[MoveOut]


class PlanRunOut(BaseModel):
    at: datetime
    trigger: PlanTrigger
    solver_status: str
    objective: float | None
    duration_ms: int
    moved_count: int
    scope: dict


async def _describe(db: AsyncSession, moves) -> list[MoveOut]:
    if not moves:
        return []
    slot_ids = {m.from_slot_id for m in moves} | {m.to_slot_id for m in moves if m.to_slot_id}
    slots = {
        s.id: s
        for s in (await db.execute(select(Slot).where(Slot.id.in_(slot_ids)))).scalars().all()
    }
    doctor_ids = {m.to_doctor_id for m in moves if m.to_doctor_id}
    names = (
        {
            d.id: u.name
            for d, u in (
                await db.execute(
                    select(Doctor, User)
                    .join(User, User.id == Doctor.user_id)
                    .where(Doctor.id.in_(doctor_ids))
                )
            ).all()
        }
        if doctor_ids
        else {}
    )
    patients = {
        p.id: p.name
        for p in (
            await db.execute(select(Patient).where(Patient.id.in_({m.patient_id for m in moves})))
        )
        .scalars()
        .all()
    }
    return [
        MoveOut(
            appointment_id=str(m.appointment_id),
            patient_name=patients.get(m.patient_id, "—"),
            from_time=slots[m.from_slot_id].starts_at,
            to_time=slots[m.to_slot_id].starts_at if m.to_slot_id else None,
            to_doctor=names.get(m.to_doctor_id),
            displacement_minutes=m.displacement_minutes,
            priority=m.priority,
        )
        for m in moves
    ]


@router.post("/scheduling/replan/{doctor_id}", response_model=PlanOut)
async def replan(
    doctor_id: uuid.UUID,
    dry_run: bool = Query(False, description="solve and report without moving anyone"),
    db: AsyncSession = Depends(get_db),
    _=Depends(ADMIN),
) -> PlanOut:
    """The one-click version of "a doctor calls in sick at 9 AM"."""
    doctor = (await db.execute(select(Doctor).where(Doctor.id == doctor_id))).scalar_one_or_none()
    if doctor is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown doctor")

    result = await scheduling.replan_doctor(
        db, doctor, PlanTrigger.MANUAL, apply=not dry_run, publish=not dry_run
    )
    await db.commit()
    return PlanOut(
        solver_status=result.status,
        objective=result.objective,
        duration_ms=result.duration_ms,
        considered_slots=result.considered_slots,
        moved=result.moved_count,
        unplaced=len(result.unplaced),
        moves=await _describe(db, result.moves),
        could_not_place=await _describe(db, result.unplaced),
    )


@router.get("/scheduling/plan-runs", response_model=list[PlanRunOut])
async def plan_runs(
    limit: int = Query(20, le=200), db: AsyncSession = Depends(get_db), _=Depends(STAFF)
) -> list[PlanRunOut]:
    """Every solve this system has ever run. The "<5s" claim, with receipts."""
    rows = (
        (await db.execute(select(PlanRun).order_by(PlanRun.created_at.desc()).limit(limit)))
        .scalars()
        .all()
    )
    return [
        PlanRunOut(
            at=r.created_at,
            trigger=r.trigger,
            solver_status=r.solver_status,
            objective=float(r.objective) if r.objective is not None else None,
            duration_ms=r.duration_ms,
            moved_count=r.moved_count,
            scope=r.scope or {},
        )
        for r in rows
    ]


class ClinicRow(BaseModel):
    doctor_id: str
    doctor_name: str
    badge_id: str
    department: str
    booked: int
    unavailable_reason: str | None = None


class PendingOut(BaseModel):
    appointment_id: str
    patient_name: str
    patient_phone: str
    department: str
    was_scheduled_for: datetime
    priority: PriorityClass


@router.get("/scheduling/pending", response_model=list[PendingOut])
async def reschedule_pending(
    db: AsyncSession = Depends(get_db), _=Depends(STAFF)
) -> list[PendingOut]:
    """Patients a replan could not seat. This list existing is the point — they are
    owed an appointment, and somebody has to be able to see that."""
    from app.models import Department

    rows = (
        await db.execute(
            select(Appointment, Slot, Patient, Department)
            .join(Slot, Slot.id == Appointment.slot_id)
            .join(Patient, Patient.id == Appointment.patient_id)
            .join(Department, Department.id == Appointment.department_id)
            .where(Appointment.status == AppointmentStatus.RESCHEDULE_PENDING)
            .order_by(Appointment.priority_class, Slot.starts_at)
        )
    ).all()
    return [
        PendingOut(
            appointment_id=str(appt.id),
            patient_name=patient.name,
            patient_phone=patient.phone,
            department=dept.name,
            was_scheduled_for=slot.starts_at,
            priority=appt.priority_class,
        )
        for appt, slot, patient, dept in rows
    ]


@router.get("/scheduling/clinic", response_model=list[ClinicRow])
async def clinic(
    hospital_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(get_db),
    _=Depends(STAFF),
) -> list[ClinicRow]:
    """Who has how many patients still waiting, and who cannot see them."""
    from app.models import DoctorStatus

    q = (
        select(Doctor, User, DoctorStatus, func.count(Appointment.id))
        .join(User, User.id == Doctor.user_id)
        .outerjoin(DoctorStatus, DoctorStatus.doctor_id == Doctor.id)
        .outerjoin(Slot, Slot.doctor_id == Doctor.id)
        .outerjoin(
            Appointment,
            (Appointment.slot_id == Slot.id)
            & (Appointment.status == AppointmentStatus.BOOKED)
            & (Slot.starts_at >= func.now()),
        )
        .group_by(Doctor.id, User.id, DoctorStatus.id)
    )
    if hospital_id:
        q = q.where(Doctor.hospital_id == hospital_id)

    from app.models import Department

    departments = {d.id: d.name for d in (await db.execute(select(Department))).scalars().all()}
    out = []
    for doctor, user, status_row, booked in (await db.execute(q)).all():
        blocked = unavailability_for(status_row)
        out.append(
            ClinicRow(
                doctor_id=str(doctor.id),
                doctor_name=user.name,
                badge_id=doctor.badge_id,
                department=departments.get(doctor.department_id, "—"),
                booked=booked,
                unavailable_reason=blocked.reason if blocked else None,
            )
        )
    return sorted(out, key=lambda r: (-r.booked, r.doctor_name))


class QueueEntryOut(BaseModel):
    position: int
    appointment_id: str
    patient_name: str
    scheduled_for: datetime
    priority: PriorityClass
    predicted_wait_minutes: int | None
    noshow_prob: float | None
    doctor_name: str


@router.get("/scheduling/queue", response_model=list[QueueEntryOut])
async def queue(
    department_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _=Depends(STAFF),
) -> list[QueueEntryOut]:
    """Who is still waiting, and how long each of them will actually wait.

    The prediction is per queue *position*, not per appointment time — the honest
    question a patient asks is "how long from now", and that depends on how far the
    clinic has already slipped.
    """
    from app.services import models as ml

    rows = (
        await db.execute(
            select(Appointment, Slot, Patient, User, Doctor)
            .join(Slot, Slot.id == Appointment.slot_id)
            .join(Patient, Patient.id == Appointment.patient_id)
            .join(Doctor, Doctor.id == Slot.doctor_id)
            .join(User, User.id == Doctor.user_id)
            .where(
                Appointment.department_id == department_id,
                Appointment.status == AppointmentStatus.BOOKED,
                Slot.starts_at >= func.now(),
            )
            .order_by(Slot.starts_at)
        )
    ).all()

    out: list[QueueEntryOut] = []
    ahead_per_doctor: dict[uuid.UUID, int] = {}
    now = datetime.now(UTC)
    for position, (appt, slot, patient, user, doctor) in enumerate(rows):
        ahead = ahead_per_doctor.get(doctor.id, 0)
        ahead_per_doctor[doctor.id] = ahead + 1
        # how far behind the clinic already is, from this doctor's first waiting slot
        delay = max((now - slot.starts_at).total_seconds() / 60, 0.0)
        out.append(
            QueueEntryOut(
                position=position,
                appointment_id=str(appt.id),
                patient_name=patient.name,
                scheduled_for=slot.starts_at,
                priority=appt.priority_class,
                predicted_wait_minutes=ml.predict_wait_minutes(
                    ahead_in_queue=ahead,
                    avg_consult_minutes=doctor.avg_consult_minutes,
                    current_delay_minutes=delay,
                ),
                noshow_prob=float(appt.noshow_prob) if appt.noshow_prob is not None else None,
                doctor_name=user.name,
            )
        )
    return out

"""Channel-agnostic booking — PRD §M3.

One implementation, consumed by every channel. The PWA, WhatsApp, SMS, IVR and the
kiosk differ only in how they collect the arguments; if a rule lives in a channel
adapter instead of here, the channels will drift and the same patient will get
different answers depending on how they asked.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import events
from app.models import (
    Appointment,
    AppointmentStatus,
    Channel,
    Department,
    Doctor,
    Hospital,
    Patient,
    PriorityClass,
    Slot,
    SlotStatus,
    User,
)
from app.services import models as ml
from app.services.availability import bookable_slots

SEARCH_HORIZON_DAYS = 7


class BookingError(Exception):
    """Something the patient needs told, not a 500."""


@dataclass(frozen=True)
class Offer:
    slot_id: uuid.UUID
    doctor_id: uuid.UUID
    doctor_name: str
    department: str
    hospital: str
    starts_at: datetime
    ends_at: datetime


async def search_slots(
    db: AsyncSession,
    *,
    department_id: uuid.UUID,
    frm: datetime | None = None,
    days: int = SEARCH_HORIZON_DAYS,
    limit: int = 20,
) -> list[Offer]:
    """Open seats a patient can actually be given, presence taken into account."""
    frm = frm or datetime.now(UTC)
    slots = await bookable_slots(db, department_id, frm, frm + timedelta(days=days), now=frm)
    if not slots:
        return []

    ids = [s.doctor_id for s in slots]
    meta = {
        d.id: (u.name, dept.name, h.name)
        for d, u, dept, h in (
            await db.execute(
                select(Doctor, User, Department, Hospital)
                .join(User, User.id == Doctor.user_id)
                .join(Department, Department.id == Doctor.department_id)
                .join(Hospital, Hospital.id == Doctor.hospital_id)
                .where(Doctor.id.in_(ids))
            )
        ).all()
    }
    out = []
    for slot in slots[:limit]:
        name, dept, hosp = meta.get(slot.doctor_id, ("—", "—", "—"))
        out.append(
            Offer(
                slot_id=slot.id,
                doctor_id=slot.doctor_id,
                doctor_name=name,
                department=dept,
                hospital=hosp,
                starts_at=slot.starts_at,
                ends_at=slot.ends_at,
            )
        )
    return out


def _priority_for(patient: Patient) -> PriorityClass:
    flags = patient.priority_flags or {}
    if flags.get("elderly") or flags.get("disabled") or flags.get("pregnant"):
        return PriorityClass.PRIORITY
    return PriorityClass.GENERAL


async def _occupancy(db: AsyncSession, slot: Slot) -> int:
    return (
        await db.execute(
            select(func.count(Appointment.id)).where(
                Appointment.slot_id == slot.id,
                Appointment.status.in_(
                    [
                        AppointmentStatus.BOOKED,
                        AppointmentStatus.CHECKED_IN,
                        AppointmentStatus.IN_CONSULT,
                    ]
                ),
            )
        )
    ).scalar_one()


async def book(
    db: AsyncSession,
    *,
    patient_id: uuid.UUID,
    slot_id: uuid.UUID,
    channel: Channel,
    priority: PriorityClass | None = None,
) -> Appointment:
    """Take a seat. Re-checks capacity under the write, because the offer a patient
    is holding may be minutes old and someone else may have taken it."""
    patient = (
        await db.execute(select(Patient).where(Patient.id == patient_id))
    ).scalar_one_or_none()
    if patient is None:
        raise BookingError("we do not have a record for that patient")

    slot = (
        await db.execute(select(Slot).where(Slot.id == slot_id).with_for_update())
    ).scalar_one_or_none()
    if slot is None:
        raise BookingError("that appointment slot no longer exists")
    if slot.status == SlotStatus.BLOCKED:
        raise BookingError("that slot is not open for booking")
    if await _occupancy(db, slot) >= slot.capacity:
        raise BookingError("that slot was taken while you were choosing — please pick another")

    doctor = (await db.execute(select(Doctor).where(Doctor.id == slot.doctor_id))).scalar_one()
    appt = Appointment(
        patient_id=patient.id,
        slot_id=slot.id,
        hospital_id=doctor.hospital_id,
        department_id=doctor.department_id,
        channel=channel,
        priority_class=priority or _priority_for(patient),
        status=AppointmentStatus.BOOKED,
        token_number=await _next_token(db, slot),
        noshow_prob=ml.predict_noshow(
            booked_at=datetime.now(UTC),
            appointment_at=slot.starts_at,
            age=patient.age,
            is_female=(patient.gender or "F").upper().startswith("F"),
            handicap=bool((patient.priority_flags or {}).get("disabled")),
        ),
    )
    db.add(appt)
    if await _occupancy(db, slot) + 1 >= slot.capacity:
        slot.status = SlotStatus.FULL
    await db.flush()
    await _publish(appt, "appointment.booked")
    return appt


async def _next_token(db: AsyncSession, slot: Slot) -> int:
    same_day = (
        await db.execute(
            select(func.count(Appointment.id))
            .join(Slot, Slot.id == Appointment.slot_id)
            .where(
                Slot.doctor_id == slot.doctor_id,
                func.date(Slot.starts_at) == func.date(slot.starts_at),
            )
        )
    ).scalar_one()
    return same_day + 1


async def cancel(db: AsyncSession, *, appointment_id: uuid.UUID) -> Appointment:
    appt = await _live_appointment(db, appointment_id)
    appt.status = AppointmentStatus.CANCELLED
    slot = (await db.execute(select(Slot).where(Slot.id == appt.slot_id))).scalar_one()
    slot.status = SlotStatus.OPEN  # give the seat back
    await db.flush()
    await _publish(appt, "appointment.cancelled")
    return appt


async def reschedule(
    db: AsyncSession, *, appointment_id: uuid.UUID, to_slot_id: uuid.UUID
) -> Appointment:
    """Move a patient, keeping the chain: the old row becomes RESCHEDULED and the new
    one points back at it, exactly as an automatic replan does."""
    old = await _live_appointment(db, appointment_id)
    new = await book(
        db,
        patient_id=old.patient_id,
        slot_id=to_slot_id,
        channel=old.channel,
        priority=old.priority_class,
    )
    new.rescheduled_from = old.id

    old_slot = (await db.execute(select(Slot).where(Slot.id == old.slot_id))).scalar_one()
    old_slot.status = SlotStatus.OPEN
    old.status = AppointmentStatus.RESCHEDULED
    await db.flush()
    await _publish(new, "appointment.rescheduled")
    return new


async def _live_appointment(db: AsyncSession, appointment_id: uuid.UUID) -> Appointment:
    appt = (
        await db.execute(select(Appointment).where(Appointment.id == appointment_id))
    ).scalar_one_or_none()
    if appt is None:
        raise BookingError("we cannot find that appointment")
    if appt.status not in (
        AppointmentStatus.BOOKED,
        AppointmentStatus.RESCHEDULE_PENDING,
        AppointmentStatus.CHECKED_IN,
    ):
        raise BookingError(f"that appointment is already {appt.status.value.lower()}")
    return appt


async def _publish(appt: Appointment, topic: str) -> None:
    await events.publish(
        topic,
        {
            "appointment_id": str(appt.id),
            "patient_id": str(appt.patient_id),
            "hospital_id": str(appt.hospital_id),
            "department_id": str(appt.department_id),
            "channel": appt.channel.value,
            "status": appt.status.value,
        },
    )

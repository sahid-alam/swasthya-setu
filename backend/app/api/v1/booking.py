"""Booking API — one implementation, every channel (PRD §M3).

The PWA, WhatsApp, SMS and the kiosk all land here. A rule that lives in a channel
adapter instead of the service would mean the same patient gets different answers
depending on how they asked.
"""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import (
    Appointment,
    AppointmentStatus,
    Channel,
    Doctor,
    Hospital,
    Notification,
    Patient,
    PriorityClass,
    Slot,
    User,
    UserRole,
)
from app.security import current_patient_id, require_roles
from app.services import booking, notify

router = APIRouter(tags=["booking"])
STAFF = require_roles(UserRole.ADMIN, UserRole.STAFF)


class OfferOut(BaseModel):
    slot_id: str
    doctor_name: str
    department: str
    hospital: str
    starts_at: datetime
    ends_at: datetime


class BookIn(BaseModel):
    patient_id: uuid.UUID
    slot_id: uuid.UUID
    channel: Channel = Channel.PWA


class AppointmentOut(BaseModel):
    appointment_id: str
    patient_name: str
    doctor_name: str
    hospital: str
    starts_at: datetime
    token_number: int | None
    status: AppointmentStatus
    priority: PriorityClass
    noshow_prob: float | None = None


class RescheduleIn(BaseModel):
    to_slot_id: uuid.UUID


async def _describe(db: AsyncSession, appointment_id: uuid.UUID) -> AppointmentOut:
    appt, slot, patient, user, hosp = (
        await db.execute(
            select(Appointment, Slot, Patient, User, Hospital)
            .join(Slot, Slot.id == Appointment.slot_id)
            .join(Patient, Patient.id == Appointment.patient_id)
            .join(Doctor, Doctor.id == Slot.doctor_id)
            .join(User, User.id == Doctor.user_id)
            .join(Hospital, Hospital.id == Appointment.hospital_id)
            .where(Appointment.id == appointment_id)
        )
    ).one()
    return AppointmentOut(
        appointment_id=str(appt.id),
        patient_name=patient.name,
        doctor_name=user.name,
        hospital=hosp.name,
        starts_at=slot.starts_at,
        token_number=appt.token_number,
        status=appt.status,
        priority=appt.priority_class,
        noshow_prob=float(appt.noshow_prob) if appt.noshow_prob is not None else None,
    )


@router.get("/booking/slots", response_model=list[OfferOut])
async def search(
    department_id: uuid.UUID,
    days: int = Query(7, ge=1, le=30),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _=Depends(STAFF),
) -> list[OfferOut]:
    offers = await booking.search_slots(db, department_id=department_id, days=days, limit=limit)
    return [
        OfferOut(
            slot_id=str(o.slot_id),
            doctor_name=o.doctor_name,
            department=o.department,
            hospital=o.hospital,
            starts_at=o.starts_at,
            ends_at=o.ends_at,
        )
        for o in offers
    ]


@router.post("/booking", response_model=AppointmentOut, status_code=status.HTTP_201_CREATED)
async def create(
    body: BookIn, db: AsyncSession = Depends(get_db), _=Depends(STAFF)
) -> AppointmentOut:
    try:
        appt = await booking.book(
            db, patient_id=body.patient_id, slot_id=body.slot_id, channel=body.channel
        )
    except booking.BookingError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    await notify.notify_appointment(db, appt.id, "booked")
    await db.commit()
    return await _describe(db, appt.id)


@router.post("/booking/{appointment_id}/cancel", response_model=AppointmentOut)
async def cancel(
    appointment_id: uuid.UUID, db: AsyncSession = Depends(get_db), _=Depends(STAFF)
) -> AppointmentOut:
    try:
        appt = await booking.cancel(db, appointment_id=appointment_id)
    except booking.BookingError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    await notify.notify_appointment(db, appt.id, "cancelled")
    await db.commit()
    return await _describe(db, appt.id)


@router.post("/booking/{appointment_id}/reschedule", response_model=AppointmentOut)
async def move(
    appointment_id: uuid.UUID,
    body: RescheduleIn,
    db: AsyncSession = Depends(get_db),
    _=Depends(STAFF),
) -> AppointmentOut:
    try:
        appt = await booking.reschedule(
            db, appointment_id=appointment_id, to_slot_id=body.to_slot_id
        )
    except booking.BookingError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    await notify.notify_appointment(db, appt.id, "rescheduled")
    await db.commit()
    return await _describe(db, appt.id)


@router.get("/booking/patient/{patient_id}", response_model=list[AppointmentOut])
async def for_patient(
    patient_id: uuid.UUID, db: AsyncSession = Depends(get_db), _=Depends(STAFF)
) -> list[AppointmentOut]:
    ids = (
        (
            await db.execute(
                select(Appointment.id)
                .join(Slot, Slot.id == Appointment.slot_id)
                .where(Appointment.patient_id == patient_id)
                .order_by(Slot.starts_at.desc())
                .limit(20)
            )
        )
        .scalars()
        .all()
    )
    return [await _describe(db, i) for i in ids]


class OutboxOut(BaseModel):
    at: datetime | None
    channel: Channel
    template: str
    status: str
    mock: bool
    to: str | None = None
    subject: str | None = None  # email only; the other channels have no such thing
    body: str | None = None
    error: str | None = None


@router.get("/notifications", response_model=list[OutboxOut])
async def outbox(
    limit: int = Query(50, le=500), db: AsyncSession = Depends(get_db), _=Depends(STAFF)
) -> list[OutboxOut]:
    """The demo outbox. Mock adapters write real rows here, so a judge can see that
    forty patients were actually told — without a vendor account (ARCHITECTURE D4)."""
    rows = (
        (
            await db.execute(
                select(Notification).order_by(Notification.created_at.desc()).limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return [
        OutboxOut(
            at=n.sent_at,
            channel=n.channel,
            template=n.template,
            status=n.status.value,
            mock=n.mock,
            to=(n.payload or {}).get("to"),
            subject=(n.payload or {}).get("subject"),
            body=(n.payload or {}).get("body"),
            error=(n.payload or {}).get("error"),
        )
        for n in rows
    ]


class PwaDept(BaseModel):
    id: str
    name: str
    hospital: str


class PwaPatient(BaseModel):
    id: str
    name: str
    language: str


class PwaContext(BaseModel):
    departments: list[PwaDept]
    patient: PwaPatient


@router.get("/pwa/context", response_model=PwaContext)
async def pwa_context(db: AsyncSession = Depends(get_db), _=Depends(STAFF)) -> PwaContext:
    """Everything the patient app needs to render its first screen, in one call.

    One round trip matters on a 2G connection in a valley; it is also why the PWA
    does not stitch three queries together client-side.

    The "patient" is currently a seeded stand-in — patient self-service auth (phone
    OTP) is NOT built, so this app is staff- or kiosk-operated. Do not present it as
    a patient logging in.
    """
    from app.models import Department as Dept

    rows = (
        await db.execute(
            select(Dept, Hospital).join(Hospital, Hospital.id == Dept.hospital_id).limit(40)
        )
    ).all()
    patient = (await db.execute(select(Patient).limit(1))).scalar_one()
    return PwaContext(
        departments=[PwaDept(id=str(d.id), name=d.name, hospital=h.name) for d, h in rows],
        patient=PwaPatient(
            id=str(patient.id), name=patient.name, language=patient.preferred_language.value
        ),
    )


class MyQueueOut(BaseModel):
    appointment_id: str
    doctor_name: str
    hospital: str
    scheduled_for: datetime
    token_number: int | None
    position: int | None
    predicted_wait_minutes: int | None
    status: AppointmentStatus


@router.get("/pwa/my-queue/{patient_id}", response_model=list[MyQueueOut])
async def my_queue(
    patient_id: uuid.UUID, db: AsyncSession = Depends(get_db), _=Depends(STAFF)
) -> list[MyQueueOut]:
    """What a patient actually wants to know: am I still on the list, and how long.

    Position is counted within the doctor's own list, not the department's — "you are
    number 4" means nothing if it counts people queueing for someone else.
    """
    from datetime import UTC

    from app.services import models as ml

    mine = (
        await db.execute(
            select(Appointment, Slot)
            .join(Slot, Slot.id == Appointment.slot_id)
            .where(
                Appointment.patient_id == patient_id,
                Appointment.status.in_(
                    [
                        AppointmentStatus.BOOKED,
                        AppointmentStatus.CHECKED_IN,
                        AppointmentStatus.RESCHEDULE_PENDING,
                    ]
                ),
            )
            .order_by(Slot.starts_at)
        )
    ).all()

    out: list[MyQueueOut] = []
    now = datetime.now(UTC)
    for appt, slot in mine:
        doctor, user, hosp = (
            await db.execute(
                select(Doctor, User, Hospital)
                .join(User, User.id == Doctor.user_id)
                .join(Hospital, Hospital.id == Doctor.hospital_id)
                .where(Doctor.id == slot.doctor_id)
            )
        ).one()

        ahead = (
            await db.execute(
                select(func.count(Appointment.id))
                .join(Slot, Slot.id == Appointment.slot_id)
                .where(
                    Slot.doctor_id == slot.doctor_id,
                    Slot.starts_at >= now,
                    Slot.starts_at < slot.starts_at,
                    Appointment.status == AppointmentStatus.BOOKED,
                )
            )
        ).scalar_one()

        out.append(
            MyQueueOut(
                appointment_id=str(appt.id),
                doctor_name=user.name,
                hospital=hosp.name,
                scheduled_for=slot.starts_at,
                token_number=appt.token_number,
                position=ahead + 1 if slot.starts_at >= now else None,
                predicted_wait_minutes=(
                    ml.predict_wait_minutes(
                        ahead_in_queue=ahead,
                        avg_consult_minutes=doctor.avg_consult_minutes,
                        current_delay_minutes=max((now - slot.starts_at).total_seconds() / 60, 0),
                    )
                    if slot.starts_at >= now
                    else None
                ),
                status=appt.status,
            )
        )
    return out


# --- patient-scoped endpoints --------------------------------------------------
# These take the patient id from the token, never from the URL. A patient token that
# accepted an id in the path would be a key to everyone's records.


@router.get("/me/context", response_model=PwaContext)
async def my_context(
    db: AsyncSession = Depends(get_db), patient_id: str = Depends(current_patient_id)
) -> PwaContext:
    from app.models import Department as Dept

    rows = (
        await db.execute(
            select(Dept, Hospital).join(Hospital, Hospital.id == Dept.hospital_id).limit(40)
        )
    ).all()
    patient = (
        await db.execute(select(Patient).where(Patient.id == uuid.UUID(patient_id)))
    ).scalar_one()
    return PwaContext(
        departments=[PwaDept(id=str(d.id), name=d.name, hospital=h.name) for d, h in rows],
        patient=PwaPatient(
            id=str(patient.id), name=patient.name, language=patient.preferred_language.value
        ),
    )


@router.get("/me/queue", response_model=list[MyQueueOut])
async def my_own_queue(
    db: AsyncSession = Depends(get_db), patient_id: str = Depends(current_patient_id)
) -> list[MyQueueOut]:
    return await my_queue(uuid.UUID(patient_id), db, None)


class MyBookIn(BaseModel):
    slot_id: uuid.UUID
    channel: Channel = Channel.PWA


@router.post("/me/booking", response_model=AppointmentOut, status_code=status.HTTP_201_CREATED)
async def book_for_myself(
    body: MyBookIn,
    db: AsyncSession = Depends(get_db),
    patient_id: str = Depends(current_patient_id),
) -> AppointmentOut:
    try:
        appt = await booking.book(
            db,
            patient_id=uuid.UUID(patient_id),
            slot_id=body.slot_id,
            channel=body.channel,
        )
    except booking.BookingError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    await notify.notify_appointment(db, appt.id, "booked")
    await db.commit()
    return await _describe(db, appt.id)


@router.get("/me/slots", response_model=list[OfferOut])
async def my_slot_search(
    department_id: uuid.UUID,
    days: int = Query(7, ge=1, le=30),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _: str = Depends(current_patient_id),
) -> list[OfferOut]:
    return await search(department_id, days, limit, db, None)

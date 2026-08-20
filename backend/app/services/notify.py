"""Notification fan-out — PRD §M3.

Every attempt writes a `notifications` row, including failures. That table is the
demo outbox: it is how you show a judge that forty patients were actually told,
without a vendor account or venue internet (ARCHITECTURE D4).
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.base import AdapterError
from app.adapters.factory import messaging
from app.models import (
    Appointment,
    Channel,
    Doctor,
    Hospital,
    Notification,
    NotificationStatus,
    Patient,
    Slot,
    User,
)

log = logging.getLogger("swasthya.notify")

# A patient reached on one channel does not need the next; try in order and stop at the
# first success. Free and immediate first, SMS last because it always works and always
# costs money. Email sits ahead of SMS but behind the chat apps: in Himachal a phone is
# read within minutes and an inbox may not be read for a day. A patient with no address
# — or no linked chat — is skipped without an attempt rather than failed.
CHANNEL_ORDER = [Channel.TELEGRAM, Channel.WHATSAPP, Channel.EMAIL, Channel.SMS]


async def notify_appointment(
    db: AsyncSession, appointment_id: uuid.UUID, template: str
) -> list[Notification]:
    """Tell one patient about one appointment, on the first channel that works."""
    row = (
        await db.execute(
            select(Appointment, Slot, Patient, Doctor, User, Hospital)
            .join(Slot, Slot.id == Appointment.slot_id)
            .join(Patient, Patient.id == Appointment.patient_id)
            .join(Doctor, Doctor.id == Slot.doctor_id)
            .join(User, User.id == Doctor.user_id)
            .join(Hospital, Hospital.id == Appointment.hospital_id)
            .where(Appointment.id == appointment_id)
        )
    ).first()
    if row is None:
        log.warning("cannot notify: appointment %s not found", appointment_id)
        return []

    appt, slot, patient, _doctor, user, hospital = row
    params = {
        "doctor": user.name,
        "hospital": hospital.name,
        "when": slot.starts_at.strftime("%d %b, %H:%M"),
        "token": appt.token_number or "—",
        "language": patient.preferred_language.value,
    }
    return await _fan_out(db, appt, patient, template, params)


async def _fan_out(
    db: AsyncSession,
    appt: Appointment | None,
    patient: Patient,
    template: str,
    params: dict,
    channels: list[Channel] | None = None,
) -> list[Notification]:
    written: list[Notification] = []
    for channel in channels or CHANNEL_ORDER:
        # Where a channel reaches this patient. Email is the only one that is not the
        # phone number, and a patient without an address simply has no email channel.
        if channel == Channel.EMAIL:
            to = patient.email
        elif channel == Channel.TELEGRAM:
            to = patient.telegram_chat_id
        else:
            to = patient.phone
        if not to:
            log.warning("no %s address for patient %s", channel.value, patient.id)
            continue
        try:
            # Selection is inside the try on purpose: a live adapter whose credentials
            # are missing raises while being *built*, and that must degrade like any
            # other vendor failure rather than 500 the flow that asked for it.
            adapter = messaging(channel)
            if not adapter.handles(template):
                # Not a failure: an OTP-only route was never a way to send this, and a
                # FAILED row would read as "we tried and could not reach them".
                log.info("%s cannot carry %s; skipping", channel.value, template)
                continue
            result = await adapter.send(to=to, template=template, params=params)
        except AdapterError as exc:
            # A vendor failing must degrade, never crash a clinical flow.
            log.warning("%s adapter refused: %s", channel.value, exc)
            result = None

        note = Notification(
            appointment_id=appt.id if appt else None,
            patient_id=patient.id,
            channel=channel,
            template=template,
            payload=(result.payload if result else {"error": "adapter refused"}),
            mock=(result.mock if result else True),
            status=(result.status if result else NotificationStatus.FAILED),
            sent_at=datetime.now(UTC),
        )
        if result and result.provider_ref:
            note.payload = {**note.payload, "provider_ref": result.provider_ref}
        if result and result.error:
            note.payload = {**note.payload, "error": result.error}
        db.add(note)
        written.append(note)

        if result and result.status in (NotificationStatus.SENT, NotificationStatus.DELIVERED):
            break  # reached them; no need to also pay for an SMS

    await db.flush()
    return written


async def send_raw(
    db: AsyncSession,
    *,
    patient: Patient,
    template: str,
    params: dict,
    channels: list[Channel] | None = None,
) -> list[Notification]:
    """A message not tied to an appointment (an OTP, say). Same fan-out, same outbox —
    an auth code that bypassed the delivery log would be the one message nobody could
    audit."""
    return await _fan_out(
        db,
        None,
        patient,
        template,
        {**params, "language": patient.preferred_language.value},
        channels=channels,
    )


async def notify_replan(db: AsyncSession, result) -> int:
    """Consume a replan and tell everyone it touched.

    Moved patients get their new time. Patients nobody could seat get told that
    plainly — the whole reason RESCHEDULE_PENDING exists is so this message can be
    sent instead of the patient discovering it at the clinic door.
    """
    sent = 0
    for move in result.moves:
        target = move.rescheduled_to or move.appointment_id
        sent += len(await notify_appointment(db, target, "rescheduled"))
    for move in result.unplaced:
        sent += len(await notify_appointment(db, move.appointment_id, "reschedule_pending"))
    return sent

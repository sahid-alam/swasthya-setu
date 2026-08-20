"""Inbound channel webhooks — PRD §M3.

WhatsApp Cloud API posts inbound messages to a webhook; the parsing and the flow are
ours either way, so the vendor shape is translated at the adapter boundary and this
router only speaks our domain. The flow calls the same booking service the PWA does.
"""

import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import events
from app.adapters.whatsapp_mock import MENU, parse_reply
from app.db import get_db
from app.models import Channel, Department, Hospital, Patient, UserRole
from app.security import require_roles
from app.services import booking, notify

router = APIRouter(prefix="/channels", tags=["channels"])
STAFF = require_roles(UserRole.ADMIN, UserRole.STAFF)

# Conversation state lives in Redis, keyed by phone number, so a second worker picks
# up mid-conversation instead of dropping the patient back at the menu. The TTL is the
# whole expiry policy: an abandoned conversation costs nothing and cleans itself up.
SESSION_TTL_SECONDS = 30 * 60


def _session_key(phone: str) -> str:
    digits = "".join(c for c in phone if c.isdigit())[-10:]
    return f"chat:whatsapp:{digits}"


async def load_session(phone: str) -> dict:
    return await events.get_json(_session_key(phone)) or {"state": "menu"}


async def save_session(phone: str, session: dict) -> None:
    await events.set_json(_session_key(phone), session, SESSION_TTL_SECONDS)


async def clear_session(phone: str) -> None:
    await events.delete(_session_key(phone))


class InboundIn(BaseModel):
    """What the Cloud API webhook boils down to once vendor shape is stripped."""

    from_phone: str
    text: str


class ReplyOut(BaseModel):
    reply: str
    state: str
    booked_appointment_id: str | None = None


async def _patient_for(db: AsyncSession, phone: str) -> Patient | None:
    digits = "".join(c for c in phone if c.isdigit())[-10:]
    return (
        await db.execute(select(Patient).where(Patient.phone.endswith(digits)).limit(1))
    ).scalar_one_or_none()


@router.post("/whatsapp/inbound", response_model=ReplyOut)
async def whatsapp_inbound(
    body: InboundIn, db: AsyncSession = Depends(get_db), _=Depends(STAFF)
) -> ReplyOut:
    """One turn of the guided booking conversation.

    Load, run, save — exactly one persist point. The turn logic has eight return
    paths and sprinkling a save before each is how you end up with the one that
    forgets, silently dropping the patient back to the menu.
    """
    session = await load_session(body.from_phone)
    reply = await _turn(db, body, session)
    if reply.state != "unknown_patient":
        # a number we do not know gets an answer but no stored state; otherwise any
        # wrong number or spam sender writes a key
        await save_session(body.from_phone, session)
    return reply


async def _turn(db: AsyncSession, body: InboundIn, session: dict) -> ReplyOut:
    patient = await _patient_for(db, body.from_phone)
    if patient is None:
        return ReplyOut(
            reply="We do not have your number on file. Please visit the hospital reception once.",
            state="unknown_patient",
        )

    lang = patient.preferred_language.value
    parsed = parse_reply(body.text)

    # State beats intent while a choice is pending. "1" means "the first option I just
    # listed", not "start booking" — reading intent first sends the patient round the
    # menu forever, which is exactly what the first version of this did.
    choosing = session["state"] in ("choosing_department", "choosing_slot")
    if choosing and body.text.strip().isdigit():
        parsed = {"intent": "choose_slot", "index": int(body.text.strip())}

    if parsed["intent"] == "book":
        rows = (
            await db.execute(
                select(Department, Hospital)
                .join(Hospital, Hospital.id == Department.hospital_id)
                .limit(5)
            )
        ).all()
        session.update(state="choosing_department", departments=[str(d.id) for d, _ in rows])
        listing = "\n".join(f"{i + 1} {d.name} — {h.name}" for i, (d, h) in enumerate(rows))
        return ReplyOut(reply=f"Reply with a number:\n{listing}", state=session["state"])

    if session["state"] == "choosing_department" and parsed["intent"] == "choose_slot":
        idx = parsed["index"] - 1
        depts = session.get("departments", [])
        if not 0 <= idx < len(depts):
            return ReplyOut(
                reply="Please reply with one of the listed numbers.", state=session["state"]
            )
        offers = await booking.search_slots(db, department_id=uuid.UUID(depts[idx]), limit=5)
        if not offers:
            session["state"] = "menu"
            return ReplyOut(
                reply="No open appointments this week. Please try again later.", state="menu"
            )
        session.update(state="choosing_slot", slots=[str(o.slot_id) for o in offers])
        listing = "\n".join(
            f"{i + 1} {o.starts_at:%d %b %H:%M} — {o.doctor_name}" for i, o in enumerate(offers)
        )
        return ReplyOut(reply=f"Reply with a number:\n{listing}", state=session["state"])

    if session["state"] == "choosing_slot" and parsed["intent"] == "choose_slot":
        idx = parsed["index"] - 1
        slots = session.get("slots", [])
        if not 0 <= idx < len(slots):
            return ReplyOut(
                reply="Please reply with one of the listed numbers.", state=session["state"]
            )
        try:
            appt = await booking.book(
                db,
                patient_id=patient.id,
                slot_id=uuid.UUID(slots[idx]),
                channel=Channel.WHATSAPP,
            )
        except booking.BookingError as exc:
            session["state"] = "menu"
            return ReplyOut(reply=f"{exc}. Reply 1 to start again.", state="menu")

        await notify.notify_appointment(db, appt.id, "booked")
        await db.commit()
        session["state"] = "menu"
        return ReplyOut(
            reply=f"Confirmed. Token {appt.token_number}. We have sent you the details.",
            state="booked",
            booked_appointment_id=str(appt.id),
        )

    if parsed["intent"] == "list":
        rows = await _upcoming(db, patient.id)
        return ReplyOut(reply=rows or "You have no upcoming appointments.", state="menu")

    # Showing the menu means we are back at the menu. Leaving the state mid-choice
    # here means the patient's next digit is read as a selection from a list they can
    # no longer see.
    session["state"] = "menu"
    session.pop("departments", None)
    session.pop("slots", None)
    return ReplyOut(reply=MENU.get(lang, MENU["EN"]), state="menu")


async def _upcoming(db: AsyncSession, patient_id: uuid.UUID) -> str:
    from app.models import Appointment, AppointmentStatus, Slot

    rows = (
        await db.execute(
            select(Appointment, Slot)
            .join(Slot, Slot.id == Appointment.slot_id)
            .where(
                Appointment.patient_id == patient_id,
                Appointment.status == AppointmentStatus.BOOKED,
            )
            .order_by(Slot.starts_at)
            .limit(5)
        )
    ).all()
    return "\n".join(f"{s.starts_at:%d %b %H:%M} — token {a.token_number or '—'}" for a, s in rows)

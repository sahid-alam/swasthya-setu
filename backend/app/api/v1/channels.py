"""Inbound channel webhooks — PRD §M3.

WhatsApp Cloud API posts inbound messages to a webhook; the parsing and the flow are
ours either way, so the vendor shape is translated at the adapter boundary and this
router only speaks our domain. The flow calls the same booking service the PWA does.
"""

import hmac
import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import events
from app.adapters.base import AdapterError, CallTurn
from app.adapters.factory import telephony
from app.adapters.vapi import ToolCall, parse_tool_calls, tool_results
from app.adapters.whatsapp_mock import MENU, parse_reply
from app.config import get_settings
from app.db import get_db
from app.models import Channel, Department, Doctor, Hospital, Patient, Slot, User, UserRole
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


async def _upcoming(db: AsyncSession, patient_id: uuid.UUID, spoken: bool = False) -> str:
    """`spoken` is the voice form: no em-dashes for a TTS engine to read out, and
    three at most, because that is the ceiling a caller can hold (IVR_MAX_OPTIONS)."""
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
            .limit(IVR_MAX_OPTIONS if spoken else 5)
        )
    ).all()
    if spoken:
        return ". ".join(
            f"{s.starts_at:%d %B, %H:%M}, token {a.token_number or '—'}" for a, s in rows
        )
    return "\n".join(f"{s.starts_at:%d %b %H:%M} — token {a.token_number or '—'}" for a, s in rows)


# --------------------------------------------------------------- IVR (PRD §M3, Tier 2)
#
# A feature phone has no screen, so the flow differs from WhatsApp in the two ways that
# matter: the caller hears three options, not five (nobody holds five in their head),
# and every input is a digit, so "1" is ambiguous unless state is read before intent.

CALL_TTL_SECONDS = 5 * 60  # a call is minutes long; an abandoned one costs nothing
IVR_MAX_OPTIONS = 3

PROMPTS = {
    "EN": {
        "menu": "Welcome to Swasthya-Setu. Press 1 to book an appointment. "
        "Press 2 to hear your appointments.",
        "unknown_caller": "We do not have this number on file. "
        "Please visit the hospital reception once. Goodbye.",
        "departments": "Choose a department. {options}",
        "slots": "Choose a time. {options}",
        "option": "Press {n} for {what}.",
        "no_slots": "There are no open appointments this week. Please try again later. Goodbye.",
        "booked": "Your appointment is confirmed with {doctor} on {when}. "
        "Your token number is {token}. We have sent you a message. Goodbye.",
        "failed": "Sorry, that time has just been taken. Goodbye.",
        "upcoming": "Your appointments. {options}. Goodbye.",
        "no_upcoming": "You have no upcoming appointments. Goodbye.",
        "again": "Sorry, I did not get that. ",
    },
    "HI": {
        "menu": "स्वास्थ्य-सेतु में आपका स्वागत है। अपॉइंटमेंट बुक करने के लिए 1 दबाएं। "
        "अपने अपॉइंटमेंट सुनने के लिए 2 दबाएं।",
        "unknown_caller": "यह नंबर हमारे पास दर्ज नहीं है। कृपया एक बार अस्पताल के "
        "रिसेप्शन पर आएं। धन्यवाद।",
        "departments": "विभाग चुनें। {options}",
        "slots": "समय चुनें। {options}",
        "option": "{what} के लिए {n} दबाएं।",
        "no_slots": "इस सप्ताह कोई अपॉइंटमेंट खाली नहीं है। कृपया बाद में कोशिश करें। धन्यवाद।",
        "booked": "{when} को {doctor} के साथ आपका अपॉइंटमेंट तय हो गया है। "
        "आपका टोकन नंबर {token} है। हमने आपको संदेश भेज दिया है। धन्यवाद।",
        "failed": "क्षमा करें, यह समय अभी किसी और ने ले लिया है। धन्यवाद।",
        "upcoming": "आपके अपॉइंटमेंट। {options}। धन्यवाद।",
        "no_upcoming": "आपका कोई आगामी अपॉइंटमेंट नहीं है। धन्यवाद।",
        "again": "क्षमा करें, समझ नहीं आया। ",
    },
}


def _say(lang: str, key: str, **params: object) -> str:
    table = PROMPTS.get(lang.upper(), PROMPTS["EN"])
    return table[key].format(**params)


def _options(lang: str, labels: list[str]) -> str:
    return " ".join(_say(lang, "option", n=i + 1, what=w) for i, w in enumerate(labels))


def _call_key(call_id: str) -> str:
    return f"chat:ivr:{call_id}"


async def load_call(call_id: str) -> dict:
    return await events.get_json(_call_key(call_id)) or {"state": "menu"}


async def save_call(call_id: str, session: dict) -> None:
    await events.set_json(_call_key(call_id), session, CALL_TTL_SECONDS)


async def clear_call(call_id: str) -> None:
    await events.delete(_call_key(call_id))


class VoiceReplyOut(BaseModel):
    """What the caller hears, in our words. A real Exotel adapter renders its own
    applet payload from this and that swap changes this response model with it."""

    say: str
    gather: int | None = 1  # digits to collect; None when we are hanging up
    hangup: bool = False
    state: str
    booked_appointment_id: str | None = None


@router.post("/ivr/webhook", response_model=VoiceReplyOut)
async def ivr_webhook(
    payload: dict, db: AsyncSession = Depends(get_db), _=Depends(STAFF)
) -> VoiceReplyOut:
    """One keypress of one call. The provider's field names stop at the adapter."""
    try:
        turn = telephony().parse_call(payload)
    except AdapterError:
        # A withheld or malformed caller id. We cannot know who is calling, so the
        # caller hears why and the call ends — the provider needs a 200 with something
        # to play, not a 500 (`AdapterError`: degrade, never crash a flow).
        return VoiceReplyOut(
            say=_say("EN", "unknown_caller"), gather=None, hangup=True, state="unknown_caller"
        )

    session = await load_call(turn.call_id)
    reply = await _ivr_turn(db, turn, session)
    if reply.hangup:
        await clear_call(turn.call_id)
    else:
        await save_call(turn.call_id, session)
    return reply


async def _ivr_turn(db: AsyncSession, turn: CallTurn, session: dict) -> VoiceReplyOut:
    patient = await _patient_for(db, turn.from_phone)
    if patient is None:
        return VoiceReplyOut(
            say=_say("EN", "unknown_caller"), gather=None, hangup=True, state="unknown_caller"
        )

    lang = patient.preferred_language.value
    state = session["state"]

    def prompt(say: str, state: str) -> VoiceReplyOut:
        """Remember the clean wording. A re-prompt replays what is stored, so storing
        the apology too is how a caller who presses wrong twice hears it twice."""
        session["say"] = say
        return VoiceReplyOut(say=say, state=state)

    def again() -> VoiceReplyOut:
        return VoiceReplyOut(say=_say(lang, "again") + session["say"], state=state)

    # Silence, a nonsense press, or the call simply connecting: say the same thing
    # again and do not move. Clearing state here is how a caller ends up indexing a
    # list they can no longer hear — the digits version of the WhatsApp bug above.
    if turn.digits is None:
        return again() if session.get("say") else prompt(_say(lang, "menu"), state)

    choice = int(turn.digits)

    # State before intent: "1" while choosing a department is department one, not
    # "start booking again".
    if state == "choosing_department":
        depts = session.get("departments", [])
        if not 1 <= choice <= len(depts):
            return again()
        offers = await booking.search_slots(
            db, department_id=uuid.UUID(depts[choice - 1]), limit=IVR_MAX_OPTIONS
        )
        if not offers:
            return VoiceReplyOut(
                say=_say(lang, "no_slots"), gather=None, hangup=True, state="no_slots"
            )
        session.update(state="choosing_slot", slots=[str(o.slot_id) for o in offers])
        return prompt(
            _say(
                lang,
                "slots",
                options=_options(
                    lang, [f"{o.starts_at:%d %B, %H:%M}, {o.doctor_name}" for o in offers]
                ),
            ),
            session["state"],
        )

    if state == "choosing_slot":
        slots = session.get("slots", [])
        if not 1 <= choice <= len(slots):
            return again()
        try:
            appt = await booking.book(
                db,
                patient_id=patient.id,
                slot_id=uuid.UUID(slots[choice - 1]),
                channel=Channel.IVR,
            )
        except booking.BookingError:
            return VoiceReplyOut(say=_say(lang, "failed"), gather=None, hangup=True, state="failed")

        # The SMS is the caller's only record — a feature phone has no confirmation
        # screen to go back to.
        await notify.notify_appointment(db, appt.id, "booked")
        await db.commit()
        slot = (await db.execute(select(Slot).where(Slot.id == appt.slot_id))).scalar_one()
        doctor = (
            await db.execute(
                select(User.name)
                .join(Doctor, Doctor.user_id == User.id)
                .where(Doctor.id == slot.doctor_id)
            )
        ).scalar_one()
        return VoiceReplyOut(
            say=_say(
                lang,
                "booked",
                doctor=doctor,
                when=f"{slot.starts_at:%d %B, %H:%M}",
                token=appt.token_number,
            ),
            gather=None,
            hangup=True,
            state="booked",
            booked_appointment_id=str(appt.id),
        )

    if choice == 1:
        rows = (
            await db.execute(
                select(Department, Hospital)
                .join(Hospital, Hospital.id == Department.hospital_id)
                .limit(IVR_MAX_OPTIONS)
            )
        ).all()
        session.update(state="choosing_department", departments=[str(d.id) for d, _ in rows])
        return prompt(
            _say(
                lang,
                "departments",
                options=_options(lang, [f"{d.name}, {h.name}" for d, h in rows]),
            ),
            session["state"],
        )

    if choice == 2:
        listing = await _upcoming(db, patient.id, spoken=True)
        return VoiceReplyOut(
            say=(_say(lang, "upcoming", options=listing) if listing else _say(lang, "no_upcoming")),
            gather=None,
            hangup=True,
            state="upcoming",
        )

    session["state"] = "menu"
    session["say"] = _say(lang, "menu")
    return again()


# ------------------------------------------------- Vapi voice agent (PRD §M3, Tier 2)
#
# Vapi runs the speech and calls these tools from its own servers. The tools do exactly
# what the IVR keypad does, through the same booking service — a voice agent is a third
# way to collect the arguments, not a third set of rules. `simulators/vapi_call.py`
# posts the same envelope with no internet, which is what keeps this demoable offline.

VOICE_TTL_SECONDS = 15 * 60
VOICE_MAX_OPTIONS = 3


def _voice_key(call_id: str) -> str:
    return f"chat:vapi:{call_id}"


async def load_voice(call_id: str) -> dict:
    return await events.get_json(_voice_key(call_id)) or {}


async def save_voice(call_id: str, session: dict) -> None:
    await events.set_json(_voice_key(call_id), session, VOICE_TTL_SECONDS)


class ToolResultsOut(BaseModel):
    results: list[dict]


@router.post("/vapi/tools", response_model=ToolResultsOut)
async def vapi_tools(
    payload: dict,
    x_setu_tool_secret: str = Header(default=""),
    db: AsyncSession = Depends(get_db),
) -> ToolResultsOut:
    """One batch of tool calls from a voice conversation.

    Not staff-authenticated: Vapi cannot hold our JWT. It is authenticated by a shared
    secret it sends as a header, and with no secret configured the endpoint refuses to
    exist rather than standing open on a public URL.
    """
    secret = get_settings().vapi_tool_secret
    if not secret:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "voice tools are not configured")
    if not hmac.compare_digest(x_setu_tool_secret, secret):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "bad tool secret")

    try:
        call_id, calls = parse_tool_calls(payload)
    except AdapterError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    session = await load_voice(call_id)
    results = []
    for call in calls:
        results.append((call.id, await _voice_tool(db, call, session)))
    await save_voice(call_id, session)
    await db.commit()
    return ToolResultsOut(**tool_results(results))


async def _voice_tool(db: AsyncSession, call: ToolCall, session: dict) -> str:
    """Every branch returns a sentence, because the result is read aloud verbatim."""
    args = call.arguments

    if call.name == "find_patient":
        patient = await _patient_for(db, str(args.get("phone", "")))
        if patient is None:
            return (
                "That number is not on file. Ask them to visit the hospital reception "
                "once to register, then try again."
            )
        session["patient_id"] = str(patient.id)
        session["patient_name"] = patient.name
        return f"Found {patient.name}. Ask which department they need."

    if call.name == "find_slots":
        wanted = str(args.get("department", "")).strip().lower()
        rows = (
            await db.execute(
                select(Department, Hospital).join(Hospital, Hospital.id == Department.hospital_id)
            )
        ).all()
        match = next((d for d, _ in rows if wanted and wanted in d.name.lower()), None)
        if match is None:
            names = ", ".join(sorted({d.name for d, _ in rows})[:6])
            return f"No department by that name. The ones we have are: {names}."

        offers = await booking.search_slots(db, department_id=match.id, limit=VOICE_MAX_OPTIONS)
        if not offers:
            return f"There is nothing open in {match.name} this week."
        session["slots"] = [str(o.slot_id) for o in offers]
        listing = "; ".join(
            f"option {i + 1}, {o.starts_at:%d %B at %H:%M} with {o.doctor_name}"
            for i, o in enumerate(offers)
        )
        return f"{match.name} has {listing}. Ask which option they want."

    if call.name == "book_slot":
        if not session.get("patient_id"):
            return "Nobody is identified yet. Ask for their phone number first."
        slots = session.get("slots") or []
        try:
            choice = int(args.get("option", 0))
        except (TypeError, ValueError):
            choice = 0
        if not 1 <= choice <= len(slots):
            return f"That is not one of the options. There are {len(slots)}."

        try:
            appt = await booking.book(
                db,
                patient_id=uuid.UUID(session["patient_id"]),
                slot_id=uuid.UUID(slots[choice - 1]),
                channel=Channel.VOICE,
            )
        except booking.BookingError as exc:
            return f"That did not go through: {exc}. Offer another option."

        await notify.notify_appointment(db, appt.id, "booked")
        session.pop("slots", None)
        return (
            f"Booked. Token number {appt.token_number}. "
            "Tell them a confirmation message is on its way."
        )

    return f"There is no tool called {call.name}."

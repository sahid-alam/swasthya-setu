"""Linking a Telegram chat to a patient — the step Telegram forces on you.

A bot cannot message someone by phone number; it can only reply to a chat that has
messaged it. So the patient opens @Swasthya_Setu_bot, taps the button Telegram itself
draws to share their contact, and Telegram hands us a phone number *it* verified along
with the chat id. That pairing is what makes a chat id trustworthy enough to send an
appointment to — we never ask the patient to type a number, because a typed number is
a claim and a shared contact is not.

Polled with `getUpdates`, not a webhook: a laptop behind NAT has no public URL, and
tying this to the demo tunnel would mean Telegram breaks whenever the tunnel restarts.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import UTC, datetime

import httpx
from sqlalchemy import select, update

from app import events
from app.adapters.telegram_real import TIMEOUT_SECONDS, api_url
from app.config import get_settings
from app.db import SessionLocal
from app.models import (
    Appointment,
    AppointmentStatus,
    Channel,
    Department,
    Doctor,
    Hospital,
    Language,
    Patient,
    Slot,
    User,
)
from app.services import booking, notify

log = logging.getLogger("swasthya.telegram")

POLL_SECONDS = 25  # long-poll: Telegram holds the request open until something happens

# Bilingual only until we know which language they want; after that every message is
# in theirs. Showing both on every turn doubles the length of a phone screen and is how
# a bot becomes unreadable.
WELCOME = (
    "<b>Swasthya-Setu</b>\n"
    "Book an appointment at a Himachal government hospital, right here.\n\n"
    "Choose a language / भाषा चुनें:\n"
    "1 English\n"
    "2 हिंदी"
)
SHARE_KEYBOARD = {
    "keyboard": [[{"text": "Share my number / मेरा नंबर साझा करें", "request_contact": True}]],
    "resize_keyboard": True,
    "one_time_keyboard": True,
}

T = {
    "EN": {
        "share": "Please share your number so we can find or create your record. "
        "Tap the button below — we never ask you to type it.",
        "welcome_back": "Welcome back, {name}.",
        "ask_name": "You are new here. What is your full name?",
        "registered": "Thank you, {name}. You are registered.",
        "menu": "What would you like to do?\n1 Book an appointment\n2 My appointments",
        "choose_dept": "Choose a department:\n{options}",
        "choose_slot": "Choose a time:\n{options}",
        "no_slots": "No open appointments there this week. Reply 1 to try another department.",
        "booked": "<b>Confirmed.</b>\n{doctor} at {hospital}\n{when}\nToken {token}",
        "failed": "{reason}. Reply 1 to start again.",
        "upcoming": "Your appointments:\n{rows}",
        "no_upcoming": "You have no upcoming appointments. Reply 1 to book one.",
        "again": "Please reply with one of the numbers listed.",
        "not_a_name": "That does not look like a name. Please type your full name.",
        "cancelled": "Cancelled: {doctor}, {when}. Reply 1 to book another.",
        "nothing_to_cancel": "You have no upcoming appointment to cancel.",
    },
    "HI": {
        "share": "अपना नंबर साझा करें ताकि हम आपका रिकॉर्ड ढूँढ या बना सकें। "
        "नीचे बटन दबाएँ — टाइप करने की ज़रूरत नहीं।",
        "welcome_back": "वापसी पर स्वागत है, {name}।",
        "ask_name": "आप यहाँ नए हैं। आपका पूरा नाम क्या है?",
        "registered": "धन्यवाद, {name}। आपका पंजीकरण हो गया है।",
        "menu": "आप क्या करना चाहेंगे?\n1 अपॉइंटमेंट बुक करें\n2 मेरे अपॉइंटमेंट",
        "choose_dept": "विभाग चुनें:\n{options}",
        "choose_slot": "समय चुनें:\n{options}",
        "no_slots": "इस सप्ताह वहाँ कोई समय खाली नहीं है। दूसरा विभाग चुनने के लिए 1 दबाएँ।",
        "booked": "<b>पुष्टि हो गई।</b>\n{hospital} में {doctor}\n{when}\nटोकन {token}",
        "failed": "{reason}। फिर से शुरू करने के लिए 1 भेजें।",
        "upcoming": "आपके अपॉइंटमेंट:\n{rows}",
        "no_upcoming": "आपका कोई आगामी अपॉइंटमेंट नहीं है। बुक करने के लिए 1 भेजें।",
        "again": "कृपया दी गई संख्याओं में से एक भेजें।",
        "not_a_name": "यह नाम जैसा नहीं लगता। कृपया अपना पूरा नाम लिखें।",
        "cancelled": "रद्द कर दिया गया: {doctor}, {when}। दूसरा बुक करने के लिए 1 भेजें।",
        "nothing_to_cancel": "रद्द करने के लिए कोई आगामी अपॉइंटमेंट नहीं है।",
    },
}


def say(lang: str, key: str, **params: object) -> str:
    return T.get(lang.upper(), T["EN"])[key].format(**params)


def _digits(phone: str) -> str:
    return "".join(c for c in phone if c.isdigit())[-10:]


async def link_contact(chat_id: str, phone: str) -> bool:
    """Point a patient row at this chat. Returns whether anyone matched."""
    async with SessionLocal() as db:
        patient = (
            await db.execute(select(Patient).where(Patient.phone.endswith(_digits(phone))).limit(1))
        ).scalar_one_or_none()
        if patient is None:
            return False
        # One chat per patient, and one patient per chat: clear any older claim on this
        # chat id first, or a shared handset silently keeps sending to the first person.
        await db.execute(
            update(Patient)
            .where(Patient.telegram_chat_id == str(chat_id))
            .values(telegram_chat_id=None)
        )
        patient.telegram_chat_id = str(chat_id)
        await db.commit()
        log.info("linked telegram chat to patient %s", patient.id)
        return True


# Conversation state lives in Redis keyed by chat, exactly like the WhatsApp flow: a
# restart or a second worker must not drop someone back to the menu mid-booking. If
# WhatsApp ever comes back as a first-class channel, these two state machines should be
# unified — they differ today because only this one registers new patients.
CHAT_TTL_SECONDS = 30 * 60


def _chat_key(chat_id: str) -> str:
    return f"chat:telegram:{chat_id}"


async def load_chat(chat_id: str) -> dict:
    return await events.get_json(_chat_key(chat_id)) or {"state": "new"}


async def save_chat(chat_id: str, session: dict) -> None:
    await events.set_json(_chat_key(chat_id), session, CHAT_TTL_SECONDS)


async def clear_chat(chat_id: str) -> None:
    await events.delete(_chat_key(chat_id))


async def register_patient(chat_id: str, phone: str, name: str, lang: str) -> Patient:
    """A patient who arrived through the bot rather than through a registrar.

    The number is Telegram's, not theirs to claim: they shared a contact and Telegram
    vouched for it, which is a stronger assertion than anything typed into a form.
    `registered_via` records the door they came in through so no screen mistakes this
    for a hospital record.
    """
    digits = _digits(phone)
    async with SessionLocal() as db:
        patient = Patient(
            name=name.strip()[:160],
            phone=digits,
            telegram_chat_id=str(chat_id),
            preferred_language=Language(lang),
            registered_via=Channel.TELEGRAM,
            priority_flags={},
        )
        db.add(patient)
        await db.commit()
        await db.refresh(patient)
        log.info("self-registered patient %s via telegram", patient.id)
        return patient


async def set_language(patient_id: uuid.UUID, lang: str) -> None:
    async with SessionLocal() as db:
        await db.execute(
            update(Patient)
            .where(Patient.id == patient_id)
            .values(preferred_language=Language(lang))
        )
        await db.commit()


async def patient_for_chat(chat_id: str) -> Patient | None:
    async with SessionLocal() as db:
        return (
            await db.execute(
                select(Patient).where(Patient.telegram_chat_id == str(chat_id)).limit(1)
            )
        ).scalar_one_or_none()


async def handle_update(http: httpx.AsyncClient, token: str, update_body: dict) -> None:
    message = update_body.get("message") or {}
    chat_id = str(((message.get("chat") or {}).get("id")) or "")
    if not chat_id:
        return

    session = await load_chat(chat_id)
    text = str(message.get("text", "")).strip()

    if text.startswith("/start"):
        session = {"state": "choosing_language"}
        await save_chat(chat_id, session)
        await _say(http, token, chat_id, WELCOME)
        return

    for reply, markup in await _turn(chat_id, session, message, text):
        await _say(http, token, chat_id, reply, **({"reply_markup": markup} if markup else {}))
    await save_chat(chat_id, session)


async def _turn(chat_id: str, session: dict, message: dict, text: str) -> list[tuple[str, dict]]:
    """Returns the messages to send. Kept free of HTTP so it can be tested as a flow."""
    contact = message.get("contact") or {}
    lang = session.get("lang") or "EN"

    if session.get("state") == "choosing_language" and text in ("1", "2"):
        lang = session["lang"] = "EN" if text == "1" else "HI"
        session["state"] = "awaiting_contact"
        return [(say(lang, "share"), SHARE_KEYBOARD)]

    if contact.get("phone_number"):
        # Telegram fills `user_id` only when the contact is the sender's own, which is
        # the difference between "this is me" and "here is a friend's number".
        own = str(contact.get("user_id") or "") == str((message.get("from") or {}).get("id") or "")
        if not own:
            return [(say(lang, "share"), SHARE_KEYBOARD)]

        session["phone"] = contact["phone_number"]
        if await link_contact(chat_id, contact["phone_number"]):
            patient = await patient_for_chat(chat_id)
            # The language they just picked wins over the one on file, and is written
            # back: answering in Hindi someone who just tapped English is the system
            # telling them their choice did not count.
            if patient and patient.preferred_language.value != lang:
                await set_language(patient.id, lang)
            session["state"] = "menu"
            return [
                (say(lang, "welcome_back", name=patient.name if patient else ""), None),
                (say(lang, "menu"), None),
            ]

        session["state"] = "awaiting_name"
        return [(say(lang, "ask_name"), None)]

    if session.get("state") == "awaiting_name":
        # One word is a name; a digit string is someone still answering the last question.
        if len(text) < 2 or text.isdigit():
            return [(say(lang, "not_a_name"), None)]
        patient = await register_patient(chat_id, session.get("phone", ""), text, lang)
        session["state"] = "menu"
        return [
            (say(lang, "registered", name=patient.name), None),
            (say(lang, "menu"), None),
        ]

    if session.get("state") == "choosing_department" and text.isdigit():
        return await _offer_slots(session, lang, int(text))

    if session.get("state") == "choosing_slot" and text.isdigit():
        return await _take_slot(chat_id, session, lang, int(text))

    if session.get("state") in (None, "new", "choosing_language") and not session.get("lang"):
        session["state"] = "choosing_language"
        return [(WELCOME, None)]

    # Every booking confirmation ends with "Reply CANCEL to cancel" — that sentence is
    # a promise, and a bot that ignores it is worse than one that never made it.
    if text.upper() in ("CANCEL", "रद्द"):
        return await _cancel_latest(chat_id, session, lang)

    if text == "1":
        return await _offer_departments(session, lang)

    if text == "2":
        return await _list_upcoming(chat_id, session, lang)

    return [(say(lang, "menu"), None)]


async def _offer_departments(session: dict, lang: str) -> list[tuple[str, dict]]:
    async with SessionLocal() as db:
        rows = (
            await db.execute(
                select(Department, Hospital)
                .join(Hospital, Hospital.id == Department.hospital_id)
                .limit(5)
            )
        ).all()
    session.update(state="choosing_department", departments=[str(d.id) for d, _ in rows])
    listing = "\n".join(f"{i + 1} {d.name} — {h.name}" for i, (d, h) in enumerate(rows))
    return [(say(lang, "choose_dept", options=listing), None)]


async def _offer_slots(session: dict, lang: str, choice: int) -> list[tuple[str, dict]]:
    depts = session.get("departments") or []
    if not 1 <= choice <= len(depts):
        return [(say(lang, "again"), None)]
    async with SessionLocal() as db:
        offers = await booking.search_slots(db, department_id=uuid.UUID(depts[choice - 1]), limit=5)
    if not offers:
        session["state"] = "menu"
        return [(say(lang, "no_slots"), None)]
    session.update(state="choosing_slot", slots=[str(o.slot_id) for o in offers])
    listing = "\n".join(
        f"{i + 1} {o.starts_at:%d %b %H:%M} — {o.doctor_name}" for i, o in enumerate(offers)
    )
    return [(say(lang, "choose_slot", options=listing), None)]


async def _take_slot(chat_id: str, session: dict, lang: str, choice: int) -> list[tuple[str, dict]]:
    slots = session.get("slots") or []
    if not 1 <= choice <= len(slots):
        return [(say(lang, "again"), None)]

    patient = await patient_for_chat(chat_id)
    if patient is None:
        session["state"] = "choosing_language"
        return [(WELCOME, None)]

    async with SessionLocal() as db:
        try:
            appt = await booking.book(
                db,
                patient_id=patient.id,
                slot_id=uuid.UUID(slots[choice - 1]),
                channel=Channel.TELEGRAM,
            )
        except booking.BookingError as exc:
            session["state"] = "menu"
            return [(say(lang, "failed", reason=str(exc)), None)]

        # The confirmation goes out through the normal fan-out, so it lands in the
        # outbox like every other message rather than being a reply nobody can audit.
        await notify.notify_appointment(db, appt.id, "booked")
        row = (
            await db.execute(
                select(Slot, User, Hospital)
                .join(Doctor, Doctor.id == Slot.doctor_id)
                .join(User, User.id == Doctor.user_id)
                .join(Hospital, Hospital.id == Doctor.hospital_id)
                .where(Slot.id == appt.slot_id)
            )
        ).one()
        await db.commit()

    slot, user, hospital = row
    session["state"] = "menu"
    session.pop("slots", None)
    return [
        (
            say(
                lang,
                "booked",
                doctor=user.name,
                hospital=hospital.name,
                when=f"{slot.starts_at:%d %b %H:%M}",
                token=appt.token_number,
            ),
            None,
        )
    ]


async def _cancel_latest(chat_id: str, session: dict, lang: str) -> list[tuple[str, dict]]:
    """The next appointment they have, not the last one booked: 'cancel' means the one
    they are about to miss."""
    patient = await patient_for_chat(chat_id)
    session["state"] = "menu"
    if patient is None:
        return [(WELCOME, None)]

    async with SessionLocal() as db:
        row = (
            await db.execute(
                select(Appointment, Slot, User)
                .join(Slot, Slot.id == Appointment.slot_id)
                .join(Doctor, Doctor.id == Slot.doctor_id)
                .join(User, User.id == Doctor.user_id)
                .where(
                    Appointment.patient_id == patient.id,
                    Appointment.status == AppointmentStatus.BOOKED,
                    # Future only. "Cancel" means the one they are about to miss, and
                    # cancelling something that already happened frees no seat and
                    # tells the patient we are not looking at a clock.
                    Slot.starts_at >= datetime.now(UTC),
                )
                .order_by(Slot.starts_at)
                .limit(1)
            )
        ).first()
        if row is None:
            return [(say(lang, "nothing_to_cancel"), None)]

        appt, slot, user = row
        await booking.cancel(db, appointment_id=appt.id)
        await db.commit()

    return [
        (
            say(lang, "cancelled", doctor=user.name, when=f"{slot.starts_at:%d %b %H:%M}"),
            None,
        )
    ]


async def _list_upcoming(chat_id: str, session: dict, lang: str) -> list[tuple[str, dict]]:
    patient = await patient_for_chat(chat_id)
    if patient is None:
        session["state"] = "choosing_language"
        return [(WELCOME, None)]
    async with SessionLocal() as db:
        rows = (
            await db.execute(
                select(Appointment, Slot, User)
                .join(Slot, Slot.id == Appointment.slot_id)
                .join(Doctor, Doctor.id == Slot.doctor_id)
                .join(User, User.id == Doctor.user_id)
                .where(
                    Appointment.patient_id == patient.id,
                    Appointment.status == AppointmentStatus.BOOKED,
                    Slot.starts_at >= datetime.now(UTC),  # "upcoming" is a claim about time
                )
                .order_by(Slot.starts_at)
                .limit(5)
            )
        ).all()
    session["state"] = "menu"
    if not rows:
        return [(say(lang, "no_upcoming"), None)]
    listing = "\n".join(
        f"{s.starts_at:%d %b %H:%M} — {u.name} — token {a.token_number or '—'}" for a, s, u in rows
    )
    return [(say(lang, "upcoming", rows=listing), None)]


async def _say(
    http: httpx.AsyncClient, token: str, chat_id: str, text: str, **extra: object
) -> None:
    try:
        await http.post(
            api_url(token, "sendMessage"),
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML", **extra},
        )
    except httpx.HTTPError as exc:  # a reply failing must not stop the poller
        log.warning("telegram reply failed: %s", exc)


async def poll_forever() -> None:
    """Consume updates until cancelled. Only started when Telegram is in live mode."""
    token = get_settings().telegram_bot_token
    offset = 0
    async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS + POLL_SECONDS) as http:
        while True:
            try:
                r = await http.get(
                    api_url(token, "getUpdates"),
                    params={"timeout": POLL_SECONDS, "offset": offset},
                )
                if not r.is_success:
                    # A revoked token or a second poller elsewhere (409) both land here,
                    # and both are silent forever otherwise.
                    log.warning("telegram getUpdates %s: %s", r.status_code, r.text[:200])
                    await asyncio.sleep(5)
                    continue
                for item in r.json().get("result") or []:
                    offset = max(offset, int(item["update_id"]) + 1)
                    log.info(
                        "telegram update %s from chat %s",
                        item.get("update_id"),
                        ((item.get("message") or {}).get("chat") or {}).get("id"),
                    )
                    await handle_update(http, token, item)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # the poller outlives any single bad update
                # Type first: httpx timeouts stringify to "", so "%s" alone produced
                # "telegram poll failed, retrying:" and told nobody anything.
                log.warning(
                    "telegram poll failed, retrying: %s: %s", type(exc).__name__, exc or "-"
                )
                await asyncio.sleep(5)

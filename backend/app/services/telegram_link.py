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

import httpx
from sqlalchemy import select, update

from app.adapters.telegram_real import TIMEOUT_SECONDS, api_url
from app.config import get_settings
from app.db import SessionLocal
from app.models import Patient

log = logging.getLogger("swasthya.telegram")

POLL_SECONDS = 25  # long-poll: Telegram holds the request open until something happens

WELCOME = (
    "<b>Swasthya-Setu</b>\n"
    "Tap the button below to link this chat to your hospital record. "
    "Then your appointment updates and login codes arrive here instead of by SMS.\n\n"
    "स्वास्थ्य-सेतु से जुड़ने के लिए नीचे दिया बटन दबाएँ।"
)
LINKED = (
    "Linked. Your appointment updates will arrive here.\n"
    "आपके अपॉइंटमेंट की जानकारी अब यहीं आएगी।"
)
UNKNOWN = (
    "That number is not on file. Please visit the hospital reception once to register.\n"
    "यह नंबर हमारे पास दर्ज नहीं है। कृपया एक बार अस्पताल के रिसेप्शन पर आएँ।"
)
SHARE_KEYBOARD = {
    "keyboard": [[{"text": "Share my number / मेरा नंबर साझा करें", "request_contact": True}]],
    "resize_keyboard": True,
    "one_time_keyboard": True,
}


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


async def handle_update(http: httpx.AsyncClient, token: str, update_body: dict) -> None:
    message = update_body.get("message") or {}
    chat_id = str(((message.get("chat") or {}).get("id")) or "")
    if not chat_id:
        return

    contact = message.get("contact") or {}
    if contact.get("phone_number"):
        # Telegram only fills `user_id` when the contact is the sender's own, which is
        # the difference between "this is me" and "here is a friend's number".
        own = str(contact.get("user_id") or "") == str((message.get("from") or {}).get("id") or "")
        matched = own and await link_contact(chat_id, contact["phone_number"])
        await _say(http, token, chat_id, LINKED if matched else UNKNOWN)
        return

    if str(message.get("text", "")).startswith("/start"):
        await _say(http, token, chat_id, WELCOME, reply_markup=SHARE_KEYBOARD)


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

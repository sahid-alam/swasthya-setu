"""Patient OTP — by phone, or by email. No new auth service: the existing messaging
adapters plus the existing JWT, with Redis holding the code for five minutes.

Security notes, because this is a trust boundary and shortcuts here are not laziness:
- codes come from `secrets`, never `random`
- comparison is constant-time
- a code dies after 5 minutes, 3 wrong guesses, or one success
- requests are rate limited per identifier, so the SMS bill is not a denial-of-wallet
- the API never reveals whether a phone or address is on file; the response is
  identical either way, and the code only ever travels to the patient's own contact
  (the mock outbox in dev)
- phone and email live in separate Redis namespaces. One keyspace would let a code
  mailed to an inbox be spent against a phone number that merely normalises the same
"""

from __future__ import annotations

import hmac
import logging
import secrets

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import events
from app.adapters.base import AdapterError, normalise_email
from app.models import Channel, Patient
from app.services import notify

log = logging.getLogger("swasthya.otp")

CODE_TTL_SECONDS = 5 * 60
MAX_ATTEMPTS = 3
MAX_REQUESTS_PER_WINDOW = 5
REQUEST_WINDOW_SECONDS = 15 * 60


def _digits(phone: str) -> str:
    return "".join(c for c in phone if c.isdigit())[-10:]


def identity(phone: str | None = None, email: str | None = None) -> tuple[str, str]:
    """`("phone", "9868553803")` or `("email", "a@b.c")` — the kind is half the Redis
    key, so the two can never be spent against each other. Exactly one is required."""
    if bool(phone) == bool(email):
        raise ValueError("give exactly one of phone, email")
    if phone:
        return "phone", _digits(phone)
    return "email", normalise_email(email or "")


def _code_key(kind: str, value: str) -> str:
    return f"otp:code:{kind}:{value}"


def _rate_key(kind: str, value: str) -> str:
    return f"otp:rate:{kind}:{value}"


def new_code() -> str:
    """Six digits, uniformly random. `secrets`, not `random` — a predictable code is
    not a code."""
    return f"{secrets.randbelow(1_000_000):06d}"


async def _within_rate_limit(kind: str, value: str) -> bool:
    key = _rate_key(kind, value)
    client = events.client()
    count = await client.incr(key)
    if count == 1:
        await client.expire(key, REQUEST_WINDOW_SECONDS)
    return count <= MAX_REQUESTS_PER_WINDOW


def _otp_channel(kind: str, via: str | None, patient: Patient) -> Channel:
    """Where this one code goes — exactly one place, never a fan-out.

    A linked Telegram chat wins over SMS for a phone login. The patient linked it for
    precisely this, the bot said so when they did, and it is free, instant and actually
    delivered — where an SMS needs a gateway this deployment does not have. `via=sms`
    forces the old behaviour for anyone who wants to see the fallback.
    """
    if kind == "email":
        return Channel.EMAIL
    if via == "sms":
        return Channel.SMS
    if patient.telegram_chat_id:
        return Channel.TELEGRAM
    return Channel.SMS


async def request_code(
    db: AsyncSession,
    phone: str | None = None,
    email: str | None = None,
    via: str | None = None,
) -> bool:
    """Returns whether a code was actually sent. Callers must NOT surface that to the
    client — the response has to look the same for a contact we do not have."""
    try:
        kind, value = identity(phone, email)
    except (ValueError, AdapterError):
        return False  # unparseable input answers exactly like an unknown patient

    if not await _within_rate_limit(kind, value):
        log.warning("otp rate limit hit for %s %s", kind, value)
        return False

    where = Patient.phone.endswith(value) if kind == "phone" else func.lower(Patient.email) == value
    patient = (await db.execute(select(Patient).where(where).limit(1))).scalar_one_or_none()
    if patient is None:
        return False

    code = new_code()
    await events.set_json(
        _code_key(kind, value),
        {"code": code, "patient_id": str(patient.id), "attempts": 0},
        CODE_TTL_SECONDS,
    )
    # Exactly one channel, never a fan-out: an OTP sent to two places is an OTP
    # delivered to whoever holds either one. A patient who asked for it on Telegram
    # gets it there — the chat is linked to this phone number by Telegram's own
    # verified contact share, so it is the same claim SMS makes, not a weaker one.
    await notify.send_raw(
        db,
        patient=patient,
        template="otp",
        params={"code": code, "minutes": CODE_TTL_SECONDS // 60},
        channels=[_otp_channel(kind, via, patient)],
    )
    return True


async def verify_code(code: str, phone: str | None = None, email: str | None = None) -> str | None:
    """Returns the patient id on success, None otherwise. Burns the code either way
    once attempts run out, so a stolen code cannot be brute-forced."""
    try:
        kind, value = identity(phone, email)
    except (ValueError, AdapterError):
        return None
    key = _code_key(kind, value)
    stored = await events.get_json(key)
    if stored is None:
        return None

    attempts = int(stored.get("attempts", 0)) + 1
    if not hmac.compare_digest(str(stored.get("code", "")), code.strip()):
        if attempts >= MAX_ATTEMPTS:
            await events.delete(key)
        else:
            await events.set_json(key, {**stored, "attempts": attempts}, CODE_TTL_SECONDS)
        return None

    await events.delete(key)  # single use
    return stored["patient_id"]

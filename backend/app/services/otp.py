"""Phone OTP for patients. No new auth service — this is the existing mock SMS
adapter plus the existing JWT, with Redis holding the code for five minutes.

Security notes, because this is a trust boundary and shortcuts here are not laziness:
- codes come from `secrets`, never `random`
- comparison is constant-time
- a code dies after 5 minutes, 3 wrong guesses, or one success
- requests are rate limited per phone, so the SMS bill is not a denial-of-wallet
- the API never reveals whether a phone is on file; the response is identical either
  way, and the code only ever travels over SMS (the mock outbox in dev)
"""

from __future__ import annotations

import hmac
import logging
import secrets

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import events
from app.models import Channel, Patient
from app.services import notify

log = logging.getLogger("swasthya.otp")

CODE_TTL_SECONDS = 5 * 60
MAX_ATTEMPTS = 3
MAX_REQUESTS_PER_WINDOW = 5
REQUEST_WINDOW_SECONDS = 15 * 60


def _digits(phone: str) -> str:
    return "".join(c for c in phone if c.isdigit())[-10:]


def _code_key(phone: str) -> str:
    return f"otp:code:{_digits(phone)}"


def _rate_key(phone: str) -> str:
    return f"otp:rate:{_digits(phone)}"


def new_code() -> str:
    """Six digits, uniformly random. `secrets`, not `random` — a predictable code is
    not a code."""
    return f"{secrets.randbelow(1_000_000):06d}"


async def _within_rate_limit(phone: str) -> bool:
    key = _rate_key(phone)
    client = events.client()
    count = await client.incr(key)
    if count == 1:
        await client.expire(key, REQUEST_WINDOW_SECONDS)
    return count <= MAX_REQUESTS_PER_WINDOW


async def request_code(db: AsyncSession, phone: str) -> bool:
    """Returns whether a code was actually sent. Callers must NOT surface that to the
    client — the response has to look the same for a number we do not have."""
    if not await _within_rate_limit(phone):
        log.warning("otp rate limit hit for %s", _digits(phone))
        return False

    patient = (
        await db.execute(select(Patient).where(Patient.phone.endswith(_digits(phone))).limit(1))
    ).scalar_one_or_none()
    if patient is None:
        return False

    code = new_code()
    await events.set_json(
        _code_key(phone),
        {"code": code, "patient_id": str(patient.id), "attempts": 0},
        CODE_TTL_SECONDS,
    )
    # SMS only. WhatsApp needs opt-in and template approval, and an auth code that
    # silently fails to reach someone is worse than one that costs a rupee.
    await notify.send_raw(
        db,
        patient=patient,
        template="otp",
        params={"code": code, "minutes": CODE_TTL_SECONDS // 60},
        channels=[Channel.SMS],
    )
    return True


async def verify_code(phone: str, code: str) -> str | None:
    """Returns the patient id on success, None otherwise. Burns the code either way
    once attempts run out, so a stolen code cannot be brute-forced."""
    key = _code_key(phone)
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

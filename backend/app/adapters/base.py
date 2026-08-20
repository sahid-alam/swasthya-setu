"""Adapter interfaces. Business logic imports from here and nowhere else.

Methods express OUR domain, not a vendor's API shape — translation happens at the
adapter boundary so a vendor swap never reaches services/.
See .claude/skills/integration-adapter/SKILL.md before adding anything here.
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from app.models import Channel, NotificationStatus


class AdapterError(Exception):
    """A vendor failed. Callers degrade — they never crash a clinical flow."""


@dataclass(frozen=True)
class DeliveryResult:
    status: NotificationStatus
    mock: bool
    provider_ref: str | None = None
    error: str | None = None
    payload: dict = field(default_factory=dict)


class MessagingAdapter(ABC):
    """Anything that can put a templated message in front of a patient."""

    channel: Channel

    @abstractmethod
    async def send(self, *, to: str, template: str, params: dict) -> DeliveryResult:
        """`to` is a phone number in our own format; the adapter normalises it."""

    @abstractmethod
    async def health(self) -> bool:
        """Cheap reachability probe; must never raise."""


@dataclass(frozen=True)
class CallTurn:
    """One webhook from a telephony provider, in our words rather than theirs.

    `digits` is None when the call has just connected and the caller has not pressed
    anything yet — which is also what an empty keypress looks like, and both mean the
    same thing to the flow: say the prompt again.
    """

    call_id: str
    from_phone: str
    digits: str | None = None


class TelephonyAdapter(ABC):
    """A phone call arriving from a provider (Exotel), translated at this boundary.

    Only the inbound direction is abstracted here, because that is the direction with
    a vendor payload in it: the provider POSTs its own field names and this turns them
    into a `CallTurn`. The reply goes back as our own domain shape — a real
    `ivr_real.py` renders the provider's applet payload instead, and that swap changes
    the webhook's response model with it.
    """

    channel: Channel

    @abstractmethod
    def parse_call(self, payload: dict) -> CallTurn:
        """Provider webhook fields → `CallTurn`. Raises `AdapterError` if unusable."""

    @abstractmethod
    async def health(self) -> bool:
        """Cheap reachability probe; must never raise."""


def render(template: str, params: dict, language: str = "EN") -> str:
    """Message bodies live here so every channel says the same thing.

    Hindi and English only (CLAUDE.md §NEVER BUILD caps language scope). Kept as
    plain strings rather than a template engine — six messages do not need one.
    """
    bodies = {
        "EN": {
            "booked": (
                "Swasthya-Setu: appointment confirmed with {doctor} at {hospital}, "
                "{when}. Token {token}. Reply CANCEL to cancel."
            ),
            # {doctor} is who the patient will NOW see, not the one who went absent —
            # naming the new doctor as "unavailable" is the obvious way to get this
            # wrong, and it reads as a system error to the person receiving it.
            "rescheduled": (
                "Swasthya-Setu: your appointment has been moved to {when} at {hospital}. "
                "You will now see {doctor}. Token {token}. Reply CANCEL if this does not suit."
            ),
            "reschedule_pending": (
                "Swasthya-Setu: {doctor} is unavailable today and we could not find you "
                "another slot. Please call {hospital} to rebook — you keep your place."
            ),
            "cancelled": "Swasthya-Setu: your appointment on {when} has been cancelled.",
            "reminder": "Swasthya-Setu: reminder — {doctor} at {hospital}, {when}. Token {token}.",
            "otp": (
                "Swasthya-Setu: your login code is {code}. It expires in {minutes} "
                "minutes. Never share it with anyone."
            ),
        },
        "HI": {
            "booked": (
                "स्वास्थ्य-सेतु: {hospital} में {doctor} के साथ आपका अपॉइंटमेंट {when} पर "
                "तय हो गया है। टोकन {token}।"
            ),
            "rescheduled": (
                "स्वास्थ्य-सेतु: आपका अपॉइंटमेंट {hospital} में {when} पर बदल दिया गया है। "
                "अब आपको {doctor} देखेंगे। टोकन {token}।"
            ),
            "reschedule_pending": (
                "स्वास्थ्य-सेतु: {doctor} आज उपलब्ध नहीं हैं और हमें दूसरा समय नहीं मिल सका। "
                "कृपया {hospital} पर संपर्क करें — आपकी बारी सुरक्षित है।"
            ),
            "cancelled": "स्वास्थ्य-सेतु: {when} का आपका अपॉइंटमेंट रद्द कर दिया गया है।",
            "reminder": "स्वास्थ्य-सेतु: याद दिलाने के लिए — {hospital} में {doctor}, {when}। टोकन {token}।",
            "otp": (
                "स्वास्थ्य-सेतु: आपका लॉगिन कोड {code} है। यह {minutes} मिनट में समाप्त हो जाएगा। "
                "इसे किसी के साथ साझा न करें।"
            ),
        },
    }
    table = bodies.get(language.upper(), bodies["EN"])
    body = table.get(template) or bodies["EN"].get(template)
    if body is None:
        raise AdapterError(f"no template named {template}")
    safe = {k: ("—" if v is None else v) for k, v in params.items()}
    try:
        return body.format(**safe)
    except KeyError as exc:
        raise AdapterError(f"template {template} needs {exc}") from exc


def normalise_phone(raw: str) -> str:
    """India: 10 digits, optionally +91 prefixed. Vendors want E.164."""
    digits = "".join(c for c in raw if c.isdigit())
    if len(digits) == 10:
        return f"+91{digits}"
    if len(digits) == 12 and digits.startswith("91"):
        return f"+{digits}"
    if raw.startswith("+"):
        return raw
    raise AdapterError(f"cannot make sense of phone number {raw!r}")


def new_ref(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"

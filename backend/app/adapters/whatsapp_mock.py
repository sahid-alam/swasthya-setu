"""Mock WhatsApp Cloud API. Same contract as SMS, plus the guided-flow reply parsing
the real Cloud API webhook would hand us."""

from __future__ import annotations

import asyncio
import random

from app.adapters.base import DeliveryResult, MessagingAdapter, new_ref, normalise_phone, render
from app.models import Channel, NotificationStatus

FAILURE_RATE = 0.02


class MockWhatsApp(MessagingAdapter):
    channel = Channel.WHATSAPP

    def __init__(self, seed: int | None = None) -> None:
        self._rng = random.Random(seed)

    async def send(self, *, to: str, template: str, params: dict) -> DeliveryResult:
        number = normalise_phone(to)
        body = render(template, params, params.get("language", "EN"))
        await asyncio.sleep(self._rng.uniform(0.05, 0.25))

        if self._rng.random() < FAILURE_RATE:
            return DeliveryResult(
                status=NotificationStatus.FAILED,
                mock=True,
                error="recipient has not opted in (simulated)",
                payload={"to": number, "body": body},
            )
        return DeliveryResult(
            # WhatsApp gives real delivery receipts, so the mock reports DELIVERED
            # rather than SENT — the distinction matters in the outbox
            status=NotificationStatus.DELIVERED,
            mock=True,
            provider_ref=new_ref("wa-mock"),
            payload={"to": number, "body": body, "type": "template"},
        )

    async def health(self) -> bool:
        return True


# --- guided booking flow ----------------------------------------------------
# The real Cloud API posts inbound messages to a webhook; parsing is ours either way,
# so it lives here and the webhook just calls it.

MENU = {
    "EN": "Reply with a number:\n1 Book an appointment\n2 My appointments\n3 Cancel",
    "HI": "एक नंबर भेजें:\n1 अपॉइंटमेंट बुक करें\n2 मेरे अपॉइंटमेंट\n3 रद्द करें",
}


def parse_reply(text: str) -> dict:
    """Turn a patient's free-text reply into an intent. Deliberately forgiving —
    people reply "1", "book", "BOOK PLS" and all of them mean the same thing."""
    cleaned = text.strip().lower()
    if cleaned in {"1", "book", "b"} or "book" in cleaned:
        return {"intent": "book"}
    if cleaned in {"2", "my", "status"} or "appointment" in cleaned:
        return {"intent": "list"}
    if cleaned in {"3", "cancel", "c"} or "cancel" in cleaned:
        return {"intent": "cancel"}
    if cleaned.isdigit():
        return {"intent": "choose_slot", "index": int(cleaned)}
    return {"intent": "unknown"}

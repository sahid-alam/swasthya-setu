"""Mock email. Same shape as the SMTP adapter to everything upstream: it takes real
time, fails occasionally, and writes a real `notifications` row you can read in the
outbox. This is the default (Iron Rule 4) — real SMTP is opt-in via `EMAIL_MOCK_MODE`.
"""

from __future__ import annotations

import asyncio
import random

from app.adapters.base import (
    DeliveryResult,
    MessagingAdapter,
    new_ref,
    normalise_email,
    render,
    subject,
)
from app.models import Channel, NotificationStatus

# Mail is more reliable than SMS and less reliable than nothing: greylisting, a full
# mailbox, a typo'd domain. If the mock never fails, the failure path never runs until
# it matters.
FAILURE_RATE = 0.02


class MockEmail(MessagingAdapter):
    channel = Channel.EMAIL

    def __init__(self, seed: int | None = None) -> None:
        self._rng = random.Random(seed)  # seedable so demos are reproducible

    async def send(self, *, to: str, template: str, params: dict) -> DeliveryResult:
        address = normalise_email(to)
        language = params.get("language", "EN")
        body = render(template, params, language)
        line = subject(template, language)
        await asyncio.sleep(self._rng.uniform(0.05, 0.3))  # realistic relay latency

        if self._rng.random() < FAILURE_RATE:
            return DeliveryResult(
                status=NotificationStatus.FAILED,
                mock=True,
                error="mailbox unavailable (simulated)",
                payload={"to": address, "subject": line, "body": body},
            )
        return DeliveryResult(
            status=NotificationStatus.SENT,
            mock=True,
            provider_ref=new_ref("smtp-mock"),
            payload={"to": address, "subject": line, "body": body},
        )

    async def health(self) -> bool:
        return True

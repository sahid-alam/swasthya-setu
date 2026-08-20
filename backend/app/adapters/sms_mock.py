"""Mock MSG91. First-class, not a stub: it takes real time, fails occasionally, and
its output is indistinguishable from the real adapter's to everything upstream."""

from __future__ import annotations

import asyncio
import random

from app.adapters.base import DeliveryResult, MessagingAdapter, new_ref, normalise_phone, render
from app.models import Channel, NotificationStatus

# A real SMS gateway drops a small share of messages. If the mock never fails, the
# failure path never gets exercised until it matters (Iron Rule 4).
FAILURE_RATE = 0.03


class MockSms(MessagingAdapter):
    channel = Channel.SMS

    def __init__(self, seed: int | None = None) -> None:
        self._rng = random.Random(seed)  # seedable so demos are reproducible

    async def send(self, *, to: str, template: str, params: dict) -> DeliveryResult:
        number = normalise_phone(to)
        body = render(template, params, params.get("language", "EN"))
        await asyncio.sleep(self._rng.uniform(0.05, 0.3))  # realistic gateway latency

        if self._rng.random() < FAILURE_RATE:
            return DeliveryResult(
                status=NotificationStatus.FAILED,
                mock=True,
                error="gateway timeout (simulated)",
                payload={"to": number, "body": body},
            )
        return DeliveryResult(
            status=NotificationStatus.SENT,
            mock=True,
            provider_ref=new_ref("msg91-mock"),
            payload={"to": number, "body": body, "segments": max(1, len(body) // 160 + 1)},
        )

    async def health(self) -> bool:
        return True

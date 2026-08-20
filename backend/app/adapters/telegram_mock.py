"""Mock Telegram. The default (Iron Rule 4) and what `make demo-check` exercises.

Same shape as the live bot to everything upstream: real latency, an occasional failure,
and a real `notifications` row in the outbox with the chat id it would have written to.
"""

from __future__ import annotations

import asyncio
import random

from app.adapters.base import DeliveryResult, MessagingAdapter, new_ref, render, subject
from app.models import Channel, NotificationStatus

# Telegram is the most reliable of the three and still not free of failure: a user can
# block the bot, and that comes back as an error rather than silence.
FAILURE_RATE = 0.02


class MockTelegram(MessagingAdapter):
    channel = Channel.TELEGRAM

    def __init__(self, seed: int | None = None) -> None:
        self._rng = random.Random(seed)

    async def send(self, *, to: str, template: str, params: dict) -> DeliveryResult:
        language = params.get("language", "EN")
        body = f"*{subject(template, language)}*\n{render(template, params, language)}"
        await asyncio.sleep(self._rng.uniform(0.05, 0.25))

        if self._rng.random() < FAILURE_RATE:
            return DeliveryResult(
                status=NotificationStatus.FAILED,
                mock=True,
                error="bot was blocked by the user (simulated)",
                payload={"to": to, "body": body},
            )
        return DeliveryResult(
            status=NotificationStatus.SENT,
            mock=True,
            provider_ref=new_ref("tg-mock"),
            payload={"to": to, "body": body},
        )

    async def health(self) -> bool:
        return True

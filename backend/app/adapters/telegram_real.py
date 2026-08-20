"""Telegram Bot API — @Swasthya_Setu_bot.

Selected when `TELEGRAM_MOCK_MODE=false`. Set in `.env` (never in code):

    TELEGRAM_MOCK_MODE=false
    TELEGRAM_BOT_TOKEN=<from @BotFather>
    TELEGRAM_BOT_USERNAME=Swasthya_Setu_bot

**Telegram cannot be addressed by phone number.** A bot may only message a chat that
has messaged it first, so `to` here is a chat id, not a number — see
`services/telegram_link.py` for how a patient gets one. A patient who has not linked
simply has no Telegram channel and the fan-out moves on to the next one.

Free, unmetered, and it works on the cheapest Android with a data connection — which
is why it sits ahead of SMS in the channel order.
"""

from __future__ import annotations

import asyncio
import logging

import httpx

from app.adapters.base import (
    AdapterError,
    DeliveryResult,
    MessagingAdapter,
    new_ref,
    render,
    subject,
)
from app.config import get_settings
from app.models import Channel, NotificationStatus

log = logging.getLogger("swasthya.telegram")

ATTEMPTS = 3
TIMEOUT_SECONDS = 5.0
API = "https://api.telegram.org"


def api_url(token: str, method: str) -> str:
    return f"{API}/bot{token}/{method}"


class TelegramBot(MessagingAdapter):
    channel = Channel.TELEGRAM

    def __init__(self) -> None:
        s = get_settings()
        if not s.telegram_bot_token:
            raise AdapterError("TELEGRAM_MOCK_MODE is false but TELEGRAM_BOT_TOKEN is not set")
        self._token = s.telegram_bot_token

    async def send(self, *, to: str, template: str, params: dict) -> DeliveryResult:
        language = params.get("language", "EN")
        # Bold subject then the same body every other channel sends (D21). HTML rather
        # than Markdown because a doctor named O'Brien breaks Markdown and not HTML.
        body = f"<b>{subject(template, language)}</b>\n{render(template, params, language)}"
        payload = {"chat_id": to, "text": body, "parse_mode": "HTML"}

        last = "not attempted"
        async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as http:
            for attempt in range(1, ATTEMPTS + 1):
                try:
                    r = await http.post(api_url(self._token, "sendMessage"), json=payload)
                except (httpx.TimeoutException, httpx.TransportError) as exc:
                    last = f"{type(exc).__name__}: {exc}"
                    log.warning("telegram attempt %s/%s: %s", attempt, ATTEMPTS, last)
                    await asyncio.sleep(0.5 * 2 ** (attempt - 1))
                    continue

                if r.is_success:
                    result = r.json().get("result") or {}
                    return DeliveryResult(
                        status=NotificationStatus.SENT,
                        mock=False,
                        provider_ref=str(result.get("message_id") or new_ref("tg")),
                        payload={"to": to, "body": body},
                    )

                described = r.json().get("description") if r.text.startswith("{") else r.text[:200]
                last = f"{r.status_code} {described}"
                # 400 (blocked, chat not found) and 401 (bad token) do not improve with
                # a second ask; 429 carries its own retry_after and we honour it once.
                if r.status_code == 429:
                    wait = float((r.json().get("parameters") or {}).get("retry_after", 1))
                    await asyncio.sleep(min(wait, 5))
                    continue
                if r.status_code < 500:
                    break
                await asyncio.sleep(0.5 * 2 ** (attempt - 1))

        return DeliveryResult(
            status=NotificationStatus.FAILED, mock=False, error=last, payload={"to": to}
        )

    async def health(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as http:
                r = await http.get(api_url(self._token, "getMe"))
            return r.is_success
        except Exception:  # a health probe that raises is not a health probe
            return False

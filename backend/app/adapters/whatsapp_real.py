"""Meta WhatsApp Cloud API — the real sender.

Selected only when `WHATSAPP_MOCK_MODE=false`. Set in `.env` (never in code):

    WHATSAPP_MOCK_MODE=false
    WHATSAPP_TOKEN=<access token from the app's WhatsApp panel>
    WHATSAPP_PHONE_NUMBER_ID=<the test number's id, NOT the number itself>
    WHATSAPP_API_VERSION=v21.0
    WHATSAPP_TEMPLATES={"otp": {"name": "setu_otp", "lang": "en", "params": ["code"]}}

**The 24-hour rule is the thing that will bite.** Meta only allows free-form text to a
user who has messaged your number in the last 24 hours. Outside that window nothing
goes through except a template Meta has approved. So:

- if `WHATSAPP_TEMPLATES` names this message, it goes as that template and works cold;
- otherwise it goes as text, which is fine inside the window and rejected outside it,
  with Meta's own reason recorded in the outbox rather than a shrug.

On a test number, the recipient must also be on the app's verified-recipients list.
None of this applies in mock mode, which is the default and what the demo runs.
"""

from __future__ import annotations

import asyncio
import json
import logging

import httpx

from app.adapters.base import (
    AdapterError,
    DeliveryResult,
    MessagingAdapter,
    normalise_phone,
    render,
)
from app.config import get_settings
from app.models import Channel, NotificationStatus

log = logging.getLogger("swasthya.whatsapp")

ATTEMPTS = 3
TIMEOUT_SECONDS = 5.0
# Meta's code for "this needs a template, your 24-hour window is closed". Worth naming:
# it is the difference between "our integration is broken" and "we are outside the
# window Meta gives you", and only one of those is worth waking someone up for.
OUTSIDE_WINDOW = 131047


class CloudApiWhatsApp(MessagingAdapter):
    channel = Channel.WHATSAPP

    def __init__(self) -> None:
        s = get_settings()
        if not (s.whatsapp_token and s.whatsapp_phone_number_id):
            raise AdapterError(
                "WHATSAPP_MOCK_MODE is false but WHATSAPP_TOKEN / "
                "WHATSAPP_PHONE_NUMBER_ID are not set"
            )
        self._s = s
        self._url = (
            f"https://graph.facebook.com/{s.whatsapp_api_version}"
            f"/{s.whatsapp_phone_number_id}/messages"
        )
        self._templates = self._parse_templates(s.whatsapp_templates)

    @staticmethod
    def _parse_templates(raw: str) -> dict:
        if not raw.strip():
            return {}
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise AdapterError(f"WHATSAPP_TEMPLATES is not valid JSON: {exc}") from exc

    def _payload(self, to: str, template: str, params: dict) -> dict:
        """Template if one is configured for this message, free-form text otherwise."""
        spec = self._templates.get(template)
        if spec is None:
            return {
                "messaging_product": "whatsapp",
                "to": to,
                "type": "text",
                "text": {"body": render(template, params, params.get("language", "EN"))},
            }
        return {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "template",
            "template": {
                "name": spec["name"],
                "language": {"code": spec.get("lang", "en")},
                "components": [
                    {
                        "type": "body",
                        "parameters": [
                            {"type": "text", "text": str(params.get(key, ""))}
                            for key in spec.get("params", [])
                        ],
                    }
                ],
            },
        }

    async def send(self, *, to: str, template: str, params: dict) -> DeliveryResult:
        number = normalise_phone(to)
        payload = self._payload(number, template, params)
        headers = {"Authorization": f"Bearer {self._s.whatsapp_token}"}
        sent_as = payload["type"]

        last = "not attempted"
        async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as http:
            for attempt in range(1, ATTEMPTS + 1):
                try:
                    r = await http.post(self._url, json=payload, headers=headers)
                except (httpx.TimeoutException, httpx.TransportError) as exc:
                    last = f"{type(exc).__name__}: {exc}"
                    log.warning("whatsapp attempt %s/%s: %s", attempt, ATTEMPTS, last)
                    await asyncio.sleep(0.5 * 2 ** (attempt - 1))
                    continue

                if r.is_success:
                    body = r.json()
                    return DeliveryResult(
                        status=NotificationStatus.SENT,
                        mock=False,
                        provider_ref=(body.get("messages") or [{}])[0].get("id"),
                        payload={"to": number, "sent_as": sent_as},
                    )

                error = (
                    (r.json().get("error") or {})
                    if r.headers.get("content-type", "").startswith("application/json")
                    else {}
                )
                code = error.get("code")
                last = f"{r.status_code} {error.get('message') or r.text[:200]}"
                if code == OUTSIDE_WINDOW:
                    last = (
                        f"{last} — outside the 24-hour window, so this message needs an "
                        f"approved template; add '{template}' to WHATSAPP_TEMPLATES"
                    )
                if r.status_code < 500:
                    break  # a bad token or an unapproved template fails the same way twice
                log.warning("whatsapp attempt %s/%s: %s", attempt, ATTEMPTS, last)
                await asyncio.sleep(0.5 * 2 ** (attempt - 1))

        return DeliveryResult(
            status=NotificationStatus.FAILED,
            mock=False,
            error=last,
            payload={"to": number, "sent_as": sent_as},
        )

    async def health(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as http:
                r = await http.get(
                    f"https://graph.facebook.com/{self._s.whatsapp_api_version}"
                    f"/{self._s.whatsapp_phone_number_id}",
                    headers={"Authorization": f"Bearer {self._s.whatsapp_token}"},
                )
            return r.is_success
        except Exception:  # a health probe that raises is not a health probe
            return False

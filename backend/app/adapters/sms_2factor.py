"""2Factor.in — OTP delivery to an Indian number, by voice call or SMS.

Selected with `SMS_PROVIDER`. Set in `.env` (never in code):

    SMS_MOCK_MODE=false
    SMS_PROVIDER=2factor-voice        # or 2factor-sms
    TWOFACTOR_API_KEY=<from the 2Factor console>

**Voice is the live route on purpose.** 2Factor's SMS route reports DELIVERED in their
logs and still gets carrier-filtered before it reaches the handset — a delivery receipt
from the sender is not evidence of arrival. The voice call arrives reliably, so that is
what patients get. `2factor-sms` exists for a deployment whose sender ID is approved,
and is off here.

**We generate the code, 2Factor only carries it.** Their API can mint an OTP for you;
using it would move a security decision to a vendor and split the source of truth away
from `services/otp.py`, which already handles expiry, attempts and single use.

**OTP only.** The endpoint delivers digits, not sentences, so this adapter refuses
anything else rather than reading a booking confirmation down a phone line. Those go by
Telegram or email — see `handles()`.
"""

from __future__ import annotations

import asyncio
import logging

import httpx

from app.adapters.base import AdapterError, DeliveryResult, MessagingAdapter
from app.adapters.sms_fence import over_limit
from app.config import get_settings
from app.models import Channel, NotificationStatus

log = logging.getLogger("swasthya.sms")

API = "https://2factor.in/API/V1"
ATTEMPTS = 2  # a call that did not connect is worth one retry; a bad key never is
TIMEOUT_SECONDS = 15.0  # placing a call is slower than posting a message


class TwoFactorSms(MessagingAdapter):
    channel = Channel.SMS

    def __init__(self, route: str = "VOICE") -> None:
        key = get_settings().twofactor_api_key
        if not key:
            raise AdapterError("SMS_PROVIDER is 2factor but TWOFACTOR_API_KEY is not set")
        self._key = key
        self._route = route.upper()

    def handles(self, template: str) -> bool:
        """Digits down a phone line. Anything with words in it belongs elsewhere."""
        return template == "otp"

    async def send(self, *, to: str, template: str, params: dict) -> DeliveryResult:
        # 2Factor wants a bare Indian number, no +91 and no punctuation.
        number = "".join(c for c in to if c.isdigit())[-10:]
        code = str(params.get("code", ""))
        if not code.isdigit():
            raise AdapterError("2Factor carries an OTP; this message has no code in it")

        reason = await over_limit()
        if reason:
            log.warning("refusing real %s OTP: %s", self._route, reason)
            return DeliveryResult(
                status=NotificationStatus.FAILED,
                mock=False,
                error=reason,
                payload={"to": number, "route": self._route},
            )

        url = f"{API}/{self._key}/{self._route}/{number}/{code}"
        last = "not attempted"
        async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as http:
            for attempt in range(1, ATTEMPTS + 1):
                try:
                    r = await http.get(url)
                except (httpx.TimeoutException, httpx.TransportError) as exc:
                    last = f"{type(exc).__name__}: {exc}"
                    log.warning("2factor attempt %s/%s: %s", attempt, ATTEMPTS, last)
                    await asyncio.sleep(1.0 * attempt)
                    continue

                body = r.json() if r.text.startswith("{") else {"Details": r.text[:200]}
                # 2Factor answers 200 with {"Status": "Error"} for a bad key or a
                # blocked number, so the status code alone decides nothing.
                if r.is_success and str(body.get("Status", "")).lower() == "success":
                    return DeliveryResult(
                        status=NotificationStatus.SENT,
                        mock=False,
                        provider_ref=str(body.get("Details", "")),
                        # A description, never the code: a voice row would otherwise
                        # show nothing at all in the outbox, and writing the digits
                        # into a table anyone with staff access can read would undo
                        # the point of a one-time code.
                        payload={
                            "to": number,
                            "route": self._route,
                            "body": (
                                f"{'Voice call placed' if self._route == 'VOICE' else 'SMS sent'}"
                                f" to {number} with a {len(code)}-digit code"
                            ),
                        },
                    )

                last = f"{r.status_code} {body.get('Details') or body}"
                break  # an error from 2Factor is a decision, not a hiccup

        return DeliveryResult(
            status=NotificationStatus.FAILED,
            mock=False,
            error=last,
            payload={"to": number, "route": self._route},
        )

    async def health(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as http:
                r = await http.get(f"{API}/{self._key}/BAL/SMS")
            return r.is_success and str(r.json().get("Status", "")).lower() == "success"
        except Exception:  # a health probe that raises is not a health probe
            return False

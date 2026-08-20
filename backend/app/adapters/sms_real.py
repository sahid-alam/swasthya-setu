"""SMS through an Android handset running the Traccar SMS Gateway app.

Selected when `SMS_MOCK_MODE=false`. Set in `.env` (never in code):

    SMS_MOCK_MODE=false
    SMS_GATEWAY_URL=http://192.168.1.42:8082
    SMS_GATEWAY_TOKEN=<the token the app shows on its own screen>

The phone is the gateway: it sends real SMS off a real SIM, which is why this exists at
all — a hospital in Himachal has a phone and a SIM long before it has an MSG91 account.

Two things that will bite:
- **It is a LAN address.** From inside the compose backend the phone is reachable at
  `192.168.x.x`, never `localhost`, and both machines must be on the same wifi. If the
  phone sleeps or roams, sends fail — which is exactly why the mock stays the default.
- **The payload shape is the app's, not ours.** It posts `{"to", "message"}` with the
  token in `Authorization`. If the app's screen shows something different, this is the
  one function to change.

Live SMS is for manual verification and live demos only (CLAUDE.md §Conventions). Tests
always run against the mock, `make demo-check` refuses to run against a live gateway,
and the rate limit below is a hard ceiling rather than a guideline.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

import httpx

from app import events
from app.adapters.base import (
    AdapterError,
    DeliveryResult,
    MessagingAdapter,
    new_ref,
    normalise_phone,
    render,
)
from app.config import get_settings
from app.models import Channel, NotificationStatus

log = logging.getLogger("swasthya.sms")

ATTEMPTS = 3
# Longer than an HTTP vendor's budget: this is a phone on wifi that may be asleep, and
# waking the radio to send a message is not instant.
TIMEOUT_SECONDS = 10.0

# Hard ceilings, not advice. Behind this adapter is one SIM on one handset with a real
# bill and a carrier that will treat a burst as spam. A replan that moves forty patients
# would otherwise put forty SMS through a phone in someone's pocket — so the limit is
# enforced here, at the only place that can actually send, rather than at each caller.
MAX_PER_DAY = 30
MAX_PER_MINUTE = 5


def _limit_keys(now: datetime) -> tuple[tuple[str, int, int], ...]:
    """(redis key, ceiling, ttl seconds) per window."""
    return (
        (f"sms:sent:day:{now:%Y%m%d}", MAX_PER_DAY, 48 * 3600),
        (f"sms:sent:min:{now:%Y%m%d%H%M}", MAX_PER_MINUTE, 120),
    )


async def over_limit(now: datetime | None = None) -> str | None:
    """The reason we are not sending, or None. Counts the attempt either way: a caller
    hammering a full bucket must not be able to spin it forever for free."""
    client = events.client()
    for key, ceiling, ttl in _limit_keys(now or datetime.now(UTC)):
        count = await client.incr(key)
        if count == 1:
            await client.expire(key, ttl)
        if count > ceiling:
            window = "day" if ceiling == MAX_PER_DAY else "minute"
            return f"real-SMS rate limit reached ({ceiling} per {window}); not sent"
    return None


class GatewaySms(MessagingAdapter):
    channel = Channel.SMS

    def __init__(self) -> None:
        s = get_settings()
        if not s.sms_gateway_url:
            raise AdapterError("SMS_MOCK_MODE is false but SMS_GATEWAY_URL is not set")
        self._url = s.sms_gateway_url.rstrip("/") + "/"
        self._token = s.sms_gateway_token

    async def send(self, *, to: str, template: str, params: dict) -> DeliveryResult:
        number = normalise_phone(to)
        body = render(template, params, params.get("language", "EN"))
        payload = {"to": number, "message": body}
        headers = {"Authorization": self._token} if self._token else {}

        reason = await over_limit()
        if reason:
            log.warning("refusing real SMS: %s", reason)
            return DeliveryResult(
                status=NotificationStatus.FAILED,
                mock=False,
                error=reason,
                payload={"to": number, "body": body},
            )

        last = "not attempted"
        async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as http:
            for attempt in range(1, ATTEMPTS + 1):
                try:
                    r = await http.post(self._url, json=payload, headers=headers)
                except (httpx.TimeoutException, httpx.TransportError) as exc:
                    # The usual cause is a sleeping phone, and it often answers the
                    # second time — this is the retry that earns its keep here.
                    last = f"{type(exc).__name__}: {exc}"
                    log.warning("sms gateway attempt %s/%s: %s", attempt, ATTEMPTS, last)
                    await asyncio.sleep(0.5 * 2 ** (attempt - 1))
                    continue

                if r.is_success:
                    return DeliveryResult(
                        status=NotificationStatus.SENT,
                        mock=False,
                        provider_ref=new_ref("gw"),
                        payload={
                            "to": number,
                            "body": body,
                            "segments": len(body) // 160 + 1,
                        },
                    )

                last = f"{r.status_code} {r.text[:200]}"
                if r.status_code < 500:
                    break  # a rejected token stays rejected
                await asyncio.sleep(0.5 * 2 ** (attempt - 1))

        return DeliveryResult(
            status=NotificationStatus.FAILED,
            mock=False,
            error=last,
            payload={"to": number, "body": body},
        )

    async def health(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as http:
                r = await http.get(self._url)
            # Any answer at all means the phone is awake and on the network; the app
            # may well 404 a GET, and that is still a live gateway.
            return r.status_code < 500
        except Exception:  # a health probe that raises is not a health probe
            return False

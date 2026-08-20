"""How much real outbound to a phone we allow, whatever the provider.

Shared by every live SMS/voice route because the ceiling is about the recipient and the
bill, not about which vendor happens to be configured. Behind these adapters is one
person's handset and a real balance — a replan that moves forty patients must not be
able to put forty messages or forty calls through it.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app import events

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

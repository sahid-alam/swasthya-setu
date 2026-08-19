"""Redis pub/sub bridge. Topics are documented in docs/ARCHITECTURE.md §Events."""

import json
from collections.abc import AsyncIterator

import redis.asyncio as redis

from app.config import get_settings

# Topics the dashboard WebSocket relays.
DASHBOARD_TOPICS = [
    "presence.changed",
    "appointments.replanned",
    "queue.updated",
    "bed.state_changed",
    "referral.updated",
    "alert.raised",
]

_client: redis.Redis | None = None


def client() -> redis.Redis:
    global _client
    if _client is None:
        _client = redis.from_url(get_settings().redis_url, decode_responses=True)
    return _client


async def publish(topic: str, payload: dict) -> None:
    await client().publish(topic, json.dumps(payload, default=str))


READY = "ws.ready"


async def subscribe(topics: list[str]) -> AsyncIterator[dict]:
    """Yield `{topic, payload}` for each message until the caller stops iterating.

    The first yield is always `ws.ready`: subscribing is async, so without it a client
    cannot tell whether an event published right after connecting was missed or is late.
    """
    pubsub = client().pubsub()
    await pubsub.subscribe(*topics)
    yield {"topic": READY, "payload": {"topics": topics}}
    try:
        async for msg in pubsub.listen():
            if msg["type"] != "message":
                continue
            try:
                payload = json.loads(msg["data"])
            except json.JSONDecodeError:
                payload = {"raw": msg["data"]}
            yield {"topic": msg["channel"], "payload": payload}
    finally:
        await pubsub.unsubscribe(*topics)
        await pubsub.aclose()

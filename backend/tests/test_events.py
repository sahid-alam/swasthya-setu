"""The Phase 0 exit criterion: a published Redis event reaches a dashboard client.

Publishes with the sync redis client rather than POST /dev/publish — TestClient
deadlocks if you make an HTTP call while inside a websocket_connect block.
"""

import json
import os

import pytest
import redis
from starlette.websockets import WebSocketDisconnect

from app.events import DASHBOARD_TOPICS, READY
from app.models import UserRole
from app.security import make_token

HOSP_A = "11111111-1111-1111-1111-111111111111"
HOSP_B = "22222222-2222-2222-2222-222222222222"


@pytest.fixture(scope="module")
def bus():
    return redis.from_url(os.environ["REDIS_URL"])


def connect(client, token, **params):
    """Open a dashboard socket and wait until it is actually subscribed.

    Counting subscribers instead would be wrong: a dev server on the same Redis is
    also a subscriber, so a publish could land before this socket is listening.
    """
    query = "&".join(f"{k}={v}" for k, v in {"token": token, **params}.items())
    ws = client.websocket_connect(f"/ws/dashboard?{query}")
    session = ws.__enter__()
    assert session.receive_json()["topic"] == READY
    return ws, session


def test_published_event_reaches_websocket(client, admin_token, bus):
    ws, session = connect(client, admin_token)
    try:
        bus.publish("presence.changed", json.dumps({"doctor_id": "d1", "new": "ON_ROUNDS"}))
        msg = session.receive_json()
    finally:
        ws.__exit__(None, None, None)
    assert msg["topic"] == "presence.changed"
    assert msg["payload"]["new"] == "ON_ROUNDS"


def test_events_for_another_hospital_are_filtered_out(client, admin_token, bus):
    ws, session = connect(client, admin_token, hospital_id=HOSP_A)
    try:
        bus.publish("alert.raised", json.dumps({"hospital_id": HOSP_B, "type": "other"}))
        bus.publish("alert.raised", json.dumps({"hospital_id": HOSP_A, "type": "mine"}))
        assert session.receive_json()["payload"]["type"] == "mine"
    finally:
        ws.__exit__(None, None, None)


def test_every_documented_topic_is_relayed(client, admin_token, bus):
    """docs/ARCHITECTURE.md §Events lists six topics; the dashboard relays all of them."""
    ws, session = connect(client, admin_token)
    try:
        for topic in DASHBOARD_TOPICS:
            bus.publish(topic, json.dumps({"probe": topic}))
            assert session.receive_json()["topic"] == topic
    finally:
        ws.__exit__(None, None, None)


def test_websocket_rejects_missing_token(client):
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect("/ws/dashboard"):
            pass
    assert exc.value.code == 4401


def test_websocket_rejects_patient_role(client):
    token = make_token("00000000-0000-0000-0000-000000000000", UserRole.PATIENT)
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect(f"/ws/dashboard?token={token}"):
            pass
    assert exc.value.code == 4403

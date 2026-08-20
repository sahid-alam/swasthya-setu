"""Vapi voice-agent tools — PRD §M3 (Tier 2 voice).

The speech is Vapi's. What is ours is the tool contract and the booking, and that is
what these test — with no network, which is also how the demo runs it.
"""

import uuid

import pytest

from app.adapters.base import AdapterError
from app.adapters.vapi import parse_tool_calls
from app.config import get_settings

SECRET = "test-tool-secret"


@pytest.fixture(autouse=True)
def tool_secret():
    settings = get_settings()
    before = settings.vapi_tool_secret
    settings.vapi_tool_secret = SECRET
    yield SECRET
    settings.vapi_tool_secret = before


@pytest.fixture
def caller(client):
    import os

    from sqlalchemy import NullPool, text
    from sqlalchemy.ext.asyncio import create_async_engine

    async def _one():
        engine = create_async_engine(os.environ["DATABASE_URL"], poolclass=NullPool)
        async with engine.begin() as conn:
            p = (await conn.execute(text("select phone from patients limit 1"))).scalar_one()
        await engine.dispose()
        return p

    return client.portal.call(_one)


def tool(client, call_id, name, arguments, secret=SECRET):
    return client.post(
        "/api/v1/channels/vapi/tools",
        headers={"X-Setu-Tool-Secret": secret},
        json={
            "message": {
                "type": "tool-calls",
                "call": {"id": call_id},
                "toolCallList": [{"id": "tc_1", "name": name, "arguments": arguments}],
            }
        },
    )


@pytest.fixture
def call_id():
    return f"vapi_{uuid.uuid4().hex[:12]}"


def test_a_voice_conversation_books_a_real_appointment(client, caller, call_id):
    assert (
        "Found"
        in tool(client, call_id, "find_patient", {"phone": caller}).json()["results"][0]["result"]
    )

    offered = tool(client, call_id, "find_slots", {"department": "General Medicine"}).json()
    assert "option 1" in offered["results"][0]["result"]

    booked = tool(client, call_id, "book_slot", {"option": 1}).json()["results"][0]["result"]
    assert "Booked" in booked and "Token number" in booked


def test_the_result_is_a_sentence_because_it_is_read_aloud(client, caller, call_id):
    """A JSON blob here is a JSON blob spoken to a patient."""
    said = tool(client, call_id, "find_patient", {"phone": "9990000000"}).json()["results"][0]
    assert said["toolCallId"] == "tc_1"
    assert said["result"].endswith(".") and "{" not in said["result"]


def test_booking_before_identifying_anyone_is_refused(client, call_id):
    said = tool(client, call_id, "book_slot", {"option": 1}).json()["results"][0]["result"]
    assert "phone number" in said


def test_an_unknown_department_lists_the_real_ones(client, caller, call_id):
    tool(client, call_id, "find_patient", {"phone": caller})
    said = tool(client, call_id, "find_slots", {"department": "Astrology"}).json()["results"][0][
        "result"
    ]
    assert "No department by that name" in said and "Medicine" in said


def test_a_wrong_secret_is_refused(client, caller, call_id):
    assert (
        tool(client, call_id, "find_patient", {"phone": caller}, secret="nope").status_code == 401
    )


def test_with_no_secret_configured_the_endpoint_refuses_to_exist(client, caller, call_id):
    """It lives on a public URL. Unconfigured must mean closed, not open."""
    settings = get_settings()
    settings.vapi_tool_secret = ""
    try:
        assert tool(client, call_id, "find_patient", {"phone": caller}).status_code == 503
    finally:
        settings.vapi_tool_secret = SECRET


# ------------------------------------------------------------ the envelope itself


def test_both_tool_call_shapes_parse_the_same():
    """Vapi has shipped the call flat and nested under `function`; the flow must not
    care which one arrived."""
    flat = {
        "message": {
            "type": "tool-calls",
            "call": {"id": "c1"},
            "toolCallList": [{"id": "t1", "name": "find_slots", "arguments": {"department": "x"}}],
        }
    }
    nested = {
        "message": {
            "type": "tool-calls",
            "call": {"id": "c1"},
            "toolCalls": [
                {"id": "t1", "function": {"name": "find_slots", "arguments": '{"department": "x"}'}}
            ],
        }
    }
    assert parse_tool_calls(flat) == parse_tool_calls(nested)


def test_a_message_that_is_not_a_tool_call_is_rejected_at_the_adapter():
    with pytest.raises(AdapterError):
        parse_tool_calls({"message": {"type": "status-update", "call": {"id": "c1"}}})


def test_a_tool_call_with_no_call_id_is_rejected():
    """The call id is what a conversation's state hangs on; without it, two callers
    would share one basket of offered slots."""
    with pytest.raises(AdapterError):
        parse_tool_calls(
            {"message": {"type": "tool-calls", "toolCallList": [{"id": "t", "name": "x"}]}}
        )

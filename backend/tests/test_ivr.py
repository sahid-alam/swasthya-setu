"""IVR booking — PRD §M3 accept #1, "book as a farmer with a feature phone".

The call goes through the same booking service the PWA and WhatsApp use, so what is
tested here is the keypad flow, not a third implementation of the booking rules.
"""

import uuid

import pytest


@pytest.fixture
def auth(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


@pytest.fixture
def caller(client):
    """A seeded patient's number, and a fresh call id per test."""
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


@pytest.fixture
def call_id():
    return f"CA{uuid.uuid4().hex[:16]}"


def dial(client, auth, caller, call_id, digits=None):
    payload = {"CallSid": call_id, "From": caller, "Direction": "incoming"}
    if digits is not None:
        payload["Digits"] = f'"{digits}"'
    return client.post("/api/v1/channels/ivr/webhook", headers=auth, json=payload).json()


def test_the_call_opens_on_a_menu_the_caller_can_hold_in_their_head(client, auth, caller, call_id):
    first = dial(client, auth, caller, call_id)
    assert first["state"] == "menu"
    assert first["gather"] == 1 and not first["hangup"]
    assert first["say"].count("1") and first["say"].count("2")


def test_a_whole_call_produces_a_real_appointment(client, auth, caller, call_id):
    dial(client, auth, caller, call_id)
    assert dial(client, auth, caller, call_id, "1")["state"] == "choosing_department"
    assert dial(client, auth, caller, call_id, "1")["state"] == "choosing_slot"
    done = dial(client, auth, caller, call_id, "1")

    assert done["state"] == "booked"
    assert done["hangup"] is True and done["gather"] is None
    appt_id = done["booked_appointment_id"]
    assert appt_id

    patient_id, channel = _appointment_row(client, appt_id)
    assert channel == "IVR", "the call must be recorded as the channel it came in on"

    # and it is a real appointment the rest of the system can see
    got = client.get(f"/api/v1/booking/patient/{patient_id}", headers=auth)
    assert any(a["appointment_id"] == appt_id for a in got.json())


def test_a_digit_means_the_option_just_heard_not_the_menu_command(client, auth, caller, call_id):
    """Every IVR input is a digit, so "1" is ambiguous unless state is read first:
    at the menu it means book, while choosing it means option one."""
    dial(client, auth, caller, call_id)
    dial(client, auth, caller, call_id, "1")
    # a second "1" must pick department one, not restart booking
    assert dial(client, auth, caller, call_id, "1")["state"] == "choosing_slot"


def test_silence_repeats_the_prompt_and_keeps_the_caller_in_place(client, auth, caller, call_id):
    """A caller who says nothing must hear the same list again — not be moved on and
    then index a list they can no longer hear."""
    dial(client, auth, caller, call_id)
    listing = dial(client, auth, caller, call_id, "1")
    silent = dial(client, auth, caller, call_id)

    assert silent["state"] == "choosing_department"
    assert listing["say"] in silent["say"]
    assert dial(client, auth, caller, call_id, "1")["state"] == "choosing_slot"


def test_an_out_of_range_press_is_corrected_not_crashed(client, auth, caller, call_id):
    dial(client, auth, caller, call_id)
    dial(client, auth, caller, call_id, "1")
    again = dial(client, auth, caller, call_id, "9")
    assert again["state"] == "choosing_department" and not again["hangup"]


def test_pressing_wrong_twice_does_not_stack_the_apology(client, auth, caller, call_id):
    """The session remembers the last clean prompt, not the last thing said. Storing
    the apology too means a caller who presses wrong twice hears it twice."""
    dial(client, auth, caller, call_id)
    dial(client, auth, caller, call_id, "1")
    first = dial(client, auth, caller, call_id, "9")
    second = dial(client, auth, caller, call_id, "9")
    assert first["say"] == second["say"]


def test_a_caller_we_cannot_identify_is_answered_not_dropped(client, auth):
    """A withheld or malformed caller id fails at the adapter. The provider still needs
    a 200 with something to play — AdapterError degrades, it does not crash a flow."""
    r = client.post(
        "/api/v1/channels/ivr/webhook",
        headers=auth,
        json={"CallSid": "CA-withheld", "From": "unknown"},
    )
    assert r.status_code == 200
    assert r.json()["hangup"] is True and r.json()["state"] == "unknown_caller"


def test_an_unknown_number_is_told_what_to_do_and_hung_up(client, auth, call_id):
    reply = dial(client, auth, "9990000000", call_id)
    assert reply["state"] == "unknown_caller"
    assert reply["hangup"] is True


def test_the_webhook_is_not_public(client, caller, call_id):
    r = client.post(
        "/api/v1/channels/ivr/webhook",
        json={"CallSid": call_id, "From": caller},
    )
    assert r.status_code in (401, 403)


def test_a_call_with_no_provider_fields_is_rejected_at_the_adapter(client, auth):
    """The adapter is the vendor boundary: nonsense stops there, not in the flow."""
    from app.adapters.base import AdapterError
    from app.adapters.ivr_mock import MockExotel

    with pytest.raises(AdapterError):
        MockExotel().parse_call({"foo": "bar"})


def test_the_adapter_reads_the_providers_field_names(client):
    from app.adapters.ivr_mock import MockExotel

    turn = MockExotel().parse_call({"CallSid": "CA123", "CallFrom": "9418000001", "Digits": '"2#"'})
    assert turn.call_id == "CA123"
    assert turn.from_phone == "+919418000001"
    assert turn.digits == "2"


def _appointment_row(client, appointment_id):
    """Whose appointment it is, and which channel it came in on — `AppointmentOut`
    does not carry the channel, and the channel is the point of this test."""
    import os

    from sqlalchemy import NullPool, text
    from sqlalchemy.ext.asyncio import create_async_engine

    async def _lookup():
        engine = create_async_engine(os.environ["DATABASE_URL"], poolclass=NullPool)
        async with engine.begin() as conn:
            row = (
                await conn.execute(
                    text("select patient_id, channel from appointments where id = :a"),
                    {"a": appointment_id},
                )
            ).one()
        await engine.dispose()
        return row

    return client.portal.call(_lookup)

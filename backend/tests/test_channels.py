"""WhatsApp guided booking — PRD §M3. The conversation calls the same booking service
the PWA does, so this tests the flow, not a second implementation of the rules."""

import pytest


@pytest.fixture
def auth(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


@pytest.fixture(autouse=True)
def fresh_session():
    """Conversations are in-memory and module-level, so one test must not start
    halfway through another test's flow."""
    from app.api.v1.channels import _SESSIONS

    _SESSIONS.clear()
    yield
    _SESSIONS.clear()


@pytest.fixture
def phone(client):
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


def say(client, auth, phone, text):
    return client.post(
        "/api/v1/channels/whatsapp/inbound",
        headers=auth,
        json={"from_phone": phone, "text": text},
    ).json()


def test_a_number_means_the_option_just_listed_not_the_menu_command(client, auth, phone):
    """ "1" while choosing a department must pick department 1, not restart booking.
    Reading intent before state sends the patient round the menu forever."""
    say(client, auth, phone, "hi")
    assert say(client, auth, phone, "1")["state"] == "choosing_department"
    assert say(client, auth, phone, "1")["state"] == "choosing_slot"


def test_the_whole_conversation_produces_a_real_appointment(client, auth, phone):
    say(client, auth, phone, "hi")
    say(client, auth, phone, "1")
    say(client, auth, phone, "1")
    done = say(client, auth, phone, "1")
    assert done["state"] == "booked", done
    assert done["booked_appointment_id"]

    outbox = client.get("/api/v1/notifications?limit=3", headers=auth).json()
    assert any(n["channel"] == "WHATSAPP" for n in outbox), "the patient must be told"


def test_an_out_of_range_choice_is_corrected_not_crashed(client, auth, phone):
    say(client, auth, phone, "hi")
    say(client, auth, phone, "1")
    reply = say(client, auth, phone, "99")
    assert "listed numbers" in reply["reply"]
    assert reply["state"] == "choosing_department"


def test_an_unknown_number_is_told_what_to_do(client, auth):
    reply = say(client, auth, "+919999000011", "hi")
    assert reply["state"] == "unknown_patient"
    assert "reception" in reply["reply"].lower()


def test_free_text_falls_back_to_the_menu(client, auth, phone):
    assert say(client, auth, phone, "namaste")["state"] == "menu"


def test_the_webhook_is_not_public(client, phone):
    r = client.post("/api/v1/channels/whatsapp/inbound", json={"from_phone": phone, "text": "hi"})
    assert r.status_code == 401

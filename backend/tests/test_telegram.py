"""Telegram channel — owner decision 2026-08-21, not in PRD §M3.

Free, works on any cheap Android with data, and it is the only channel where the
patient must hand us an address before we can use it at all. The linking rules are the
security-relevant part, so that is most of what is tested here.
"""

import os

import pytest
from sqlalchemy import NullPool, text
from sqlalchemy.ext.asyncio import create_async_engine

from app.services import telegram_link

CHAT = "987654321"
OTHER_CHAT = "111222333"


async def _sql(query: str, params: dict | None = None):
    # positional, not **kwargs: portal.call passes args through positionally only
    engine = create_async_engine(os.environ["DATABASE_URL"], poolclass=NullPool)
    async with engine.begin() as conn:
        result = await conn.execute(text(query), params or {})
        rows = result.all() if result.returns_rows else []
    await engine.dispose()
    return rows


@pytest.fixture
def phone(client):
    rows = client.portal.call(_sql, "select phone from patients limit 1")
    return rows[0][0]


@pytest.fixture(autouse=True)
def clean_links(client):
    yield
    client.portal.call(_sql, "update patients set telegram_chat_id = null")


def test_sharing_a_contact_links_the_chat_to_that_patient(client, phone):
    assert client.portal.call(telegram_link.link_contact, CHAT, phone) is True
    rows = client.portal.call(
        _sql, "select telegram_chat_id from patients where phone = :p", {"p": phone}
    )
    assert rows[0][0] == CHAT


def test_a_number_we_do_not_have_links_nothing(client):
    assert client.portal.call(telegram_link.link_contact, CHAT, "9990000000") is False


def test_a_chat_can_only_belong_to_one_patient(client, phone):
    """A shared handset re-linking must move the chat, not leave two patients pointed
    at it — otherwise the second person's appointments go to the first person."""
    other = client.portal.call(_sql, "select phone from patients offset 1 limit 1")[0][0]
    client.portal.call(telegram_link.link_contact, CHAT, phone)
    client.portal.call(telegram_link.link_contact, CHAT, other)

    holders = client.portal.call(
        _sql, "select phone from patients where telegram_chat_id = :c", {"c": CHAT}
    )
    assert [h[0] for h in holders] == [other]


def test_a_forwarded_contact_is_not_a_link(client, phone):
    """Telegram fills `user_id` only when the contact is the sender's own. Someone
    forwarding a friend's card must not be able to point our messages at themselves."""
    sent = []

    class FakeHttp:
        async def post(self, url, json):
            sent.append(json)
            return None

    update = {
        "message": {
            "chat": {"id": OTHER_CHAT},
            "from": {"id": 42},
            "contact": {"phone_number": phone, "user_id": 99},  # not the sender
        }
    }
    client.portal.call(telegram_link.handle_update, FakeHttp(), "token", update)

    linked = client.portal.call(
        _sql, "select telegram_chat_id from patients where phone = :p", {"p": phone}
    )
    assert linked[0][0] is None
    assert "not on file" in sent[0]["text"]


def test_start_offers_the_button_telegram_draws_itself(client):
    sent = []

    class FakeHttp:
        async def post(self, url, json):
            sent.append(json)
            return None

    client.portal.call(
        telegram_link.handle_update,
        FakeHttp(),
        "token",
        {"message": {"chat": {"id": CHAT}, "from": {"id": 1}, "text": "/start"}},
    )
    assert sent[0]["reply_markup"]["keyboard"][0][0]["request_contact"] is True


# ------------------------------------------------------------------ delivery


def test_a_linked_patient_is_reached_on_telegram_before_sms(client, phone, admin_token):
    """Telegram leads the channel order because it is free; SMS costs money per send."""
    client.portal.call(telegram_link.link_contact, CHAT, phone)

    auth = {"Authorization": f"Bearer {admin_token}"}
    assert (
        client.post(
            "/api/v1/auth/otp/request", json={"phone": phone, "via": "telegram"}
        ).status_code
        == 200
    )
    latest = next(
        r
        for r in client.get("/api/v1/notifications?limit=5", headers=auth).json()
        if r["template"] == "otp"
    )
    assert latest["channel"] == "TELEGRAM"
    assert latest["to"] == CHAT


def test_asking_for_telegram_without_a_linked_chat_still_gets_the_code(client, phone, admin_token):
    """Silently downgrading to SMS is right — an unlinked patient asking for Telegram
    has made a mistake, and the mistake must not cost them their login."""
    auth = {"Authorization": f"Bearer {admin_token}"}
    client.post("/api/v1/auth/otp/request", json={"phone": phone, "via": "telegram"})
    latest = next(
        r
        for r in client.get("/api/v1/notifications?limit=5", headers=auth).json()
        if r["template"] == "otp"
    )
    assert latest["channel"] == "SMS"

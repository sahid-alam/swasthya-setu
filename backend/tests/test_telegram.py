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
    # Only the chats these tests use. Clearing every link would unlink whoever is
    # actually holding a phone against this database — which is exactly what running
    # the suite used to do to the live demo account.
    client.portal.call(
        _sql,
        "update patients set telegram_chat_id = null where telegram_chat_id in (:a, :b)",
        {"a": CHAT, "b": OTHER_CHAT},
    )


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
    assert "share your number" in sent[0]["text"], "asked again, never linked"


def test_start_asks_for_a_language_before_anything_else(client):
    """Everything after this is in one language, so it is the first thing to settle —
    and the share button is drawn by Telegram, so the number is never typed."""
    sent = []

    class Collector:
        async def post(self, url, json):
            sent.append(json)
            return None

    http = Collector()
    for said in ("/start", "1"):
        client.portal.call(
            telegram_link.handle_update,
            http,
            "token",
            {"message": {"chat": {"id": CHAT}, "from": {"id": 1}, "text": said}},
        )

    assert "English" in sent[0]["text"] and "हिंदी" in sent[0]["text"]
    assert sent[-1]["reply_markup"]["keyboard"][0][0]["request_contact"] is True


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


# ------------------------------------------------ the conversation (self-registration)
#
# A stranger with a phone must be able to get an appointment without first becoming a
# row somebody else typed in. Telegram vouches for the number, which is a stronger
# claim than a typed one — that is what makes registering them here defensible.

NEW_CHAT = "555000111"
NEW_PHONE = "+919000000123"


class FakeHttp:
    """Collects what the bot would say, so the flow is testable without a network."""

    def __init__(self):
        self.sent = []

    async def post(self, url, json):
        self.sent.append(json)
        return None

    def texts(self):
        return [m["text"] for m in self.sent]


@pytest.fixture(autouse=True)
def clean_chat(client):
    async def _wipe():
        from app.services.telegram_link import clear_chat

        await clear_chat(NEW_CHAT)
        await clear_chat(CHAT)

    client.portal.call(_wipe)
    yield
    client.portal.call(_wipe)
    # By phone as well as chat id: the other autouse fixture nulls every chat id on
    # teardown, so a delete keyed only on chat id matches nothing and the registered
    # patient survives into the next test.
    client.portal.call(
        _sql,
        "delete from patients where telegram_chat_id = :c or phone = :p",
        {"c": NEW_CHAT, "p": NEW_PHONE[-10:]},
    )


def send(client, http, chat, **message):
    client.portal.call(
        telegram_link.handle_update,
        http,
        "token",
        {"message": {"chat": {"id": chat}, "from": {"id": 42}, **message}},
    )


def test_a_stranger_can_register_and_book_without_visiting_reception(client):
    http = FakeHttp()

    send(client, http, NEW_CHAT, text="/start")
    assert "भाषा चुनें" in http.texts()[-1], "language first, before anything else"

    send(client, http, NEW_CHAT, text="1")  # English
    assert "share your number" in http.texts()[-1]

    send(client, http, NEW_CHAT, contact={"phone_number": NEW_PHONE, "user_id": 42})
    assert "new here" in http.texts()[-1], "an unknown number must be offered a way in"

    send(client, http, NEW_CHAT, text="Asha Devi")
    assert "registered" in http.texts()[-2]

    rows = client.portal.call(
        _sql,
        "select name, registered_via from patients where telegram_chat_id = :c",
        {"c": NEW_CHAT},
    )
    assert rows[0][0] == "Asha Devi"
    assert rows[0][1] == "TELEGRAM", "a self-registration must not look like a hospital record"

    send(client, http, NEW_CHAT, text="1")  # book
    assert "Choose a department" in http.texts()[-1]
    send(client, http, NEW_CHAT, text="1")
    assert "Choose a time" in http.texts()[-1]
    send(client, http, NEW_CHAT, text="1")
    assert "Confirmed" in http.texts()[-1] and "Token" in http.texts()[-1]

    booked = client.portal.call(
        _sql,
        "select a.channel from appointments a join patients p on p.id = a.patient_id "
        "where p.telegram_chat_id = :c",
        {"c": NEW_CHAT},
    )
    assert [b[0] for b in booked] == ["TELEGRAM"]


def test_hindi_is_a_real_choice_not_a_label(client):
    http = FakeHttp()
    send(client, http, NEW_CHAT, text="/start")
    send(client, http, NEW_CHAT, text="2")  # हिंदी
    assert "नंबर साझा करें" in http.texts()[-1]

    send(client, http, NEW_CHAT, contact={"phone_number": NEW_PHONE, "user_id": 42})
    assert "पूरा नाम" in http.texts()[-1], "the whole flow follows the choice, not just one line"


def test_an_existing_patient_is_greeted_not_re_registered(client, phone):
    http = FakeHttp()
    send(client, http, CHAT, text="/start")
    send(client, http, CHAT, text="1")
    send(client, http, CHAT, contact={"phone_number": phone, "user_id": 42})

    assert "Welcome back" in http.texts()[-2]
    rows = client.portal.call(
        _sql, "select registered_via from patients where phone = :p", {"p": phone}
    )
    assert rows[0][0] is None, "an existing record must not be relabelled as self-registered"


def test_a_forwarded_contact_cannot_register_anyone(client):
    """Someone else's contact card is not consent, and not a verified number."""
    http = FakeHttp()
    send(client, http, NEW_CHAT, text="/start")
    send(client, http, NEW_CHAT, text="1")
    send(client, http, NEW_CHAT, contact={"phone_number": NEW_PHONE, "user_id": 99})

    assert "share your number" in http.texts()[-1]
    rows = client.portal.call(
        _sql, "select 1 from patients where telegram_chat_id = :c", {"c": NEW_CHAT}
    )
    assert not rows


def test_a_number_that_is_not_a_name_is_asked_again(client):
    http = FakeHttp()
    send(client, http, NEW_CHAT, text="/start")
    send(client, http, NEW_CHAT, text="1")
    send(client, http, NEW_CHAT, contact={"phone_number": NEW_PHONE, "user_id": 42})
    send(client, http, NEW_CHAT, text="12345")
    assert "does not look like a name" in http.texts()[-1]


def test_reply_cancel_actually_cancels(client):
    """Every confirmation ends with 'Reply CANCEL to cancel'. That sentence is a
    promise the bot has to keep, and it frees the seat for someone else."""
    http = FakeHttp()
    send(client, http, NEW_CHAT, text="/start")
    send(client, http, NEW_CHAT, text="1")
    send(client, http, NEW_CHAT, contact={"phone_number": NEW_PHONE, "user_id": 42})
    send(client, http, NEW_CHAT, text="Asha Devi")
    for step in ("1", "1", "1"):
        send(client, http, NEW_CHAT, text=step)
    assert "Confirmed" in http.texts()[-1]

    send(client, http, NEW_CHAT, text="CANCEL")
    assert "Cancelled" in http.texts()[-1]

    rows = client.portal.call(
        _sql,
        "select a.status from appointments a join patients p on p.id = a.patient_id "
        "where p.telegram_chat_id = :c",
        {"c": NEW_CHAT},
    )
    assert [r[0] for r in rows] == ["CANCELLED"]


def test_cancel_with_nothing_booked_says_so(client, phone):
    http = FakeHttp()
    send(client, http, NEW_CHAT, text="/start")
    send(client, http, NEW_CHAT, text="2")  # हिंदी
    send(client, http, NEW_CHAT, contact={"phone_number": NEW_PHONE, "user_id": 42})
    send(client, http, NEW_CHAT, text="आशा देवी")
    send(client, http, NEW_CHAT, text="CANCEL")
    assert "रद्द करने के लिए" in http.texts()[-1], "and in their language, not ours"

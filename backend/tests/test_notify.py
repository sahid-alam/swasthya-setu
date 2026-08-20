"""Notification fan-out and the message bodies patients actually receive."""

import pytest

from app.adapters.base import AdapterError, DeliveryResult, normalise_phone, render
from app.adapters.whatsapp_mock import parse_reply
from app.models import Channel, NotificationStatus

PARAMS = {"doctor": "Dr. Sunita Sharma", "hospital": "IGMC", "when": "20 Aug, 15:30", "token": 7}


def test_rescheduled_message_names_the_doctor_the_patient_will_now_see():
    """Naming the *new* doctor as unavailable reads as a system error to the patient —
    which is exactly what the first version of this template did."""
    body = render("rescheduled", PARAMS)
    assert "Dr. Sunita Sharma" in body
    assert "unavailable" not in body.lower()
    assert "moved" in body.lower()


def test_pending_message_tells_the_patient_what_to_do():
    body = render("reschedule_pending", {"doctor": "Dr. X", "hospital": "IGMC"})
    assert "call" in body.lower()
    assert "keep your place" in body.lower()


def test_hindi_is_actually_hindi_not_a_fallback():
    body = render("booked", PARAMS, "HI")
    assert "स्वास्थ्य-सेतु" in body
    assert body != render("booked", PARAMS, "EN")


def test_an_unknown_language_falls_back_to_english_rather_than_failing():
    assert render("booked", PARAMS, "TA") == render("booked", PARAMS, "EN")


def test_a_missing_template_is_a_loud_error():
    with pytest.raises(AdapterError):
        render("no_such_template", PARAMS)


def test_phone_numbers_are_normalised_to_e164():
    assert normalise_phone("9418000001") == "+919418000001"
    assert normalise_phone("+91 94180 00001") == "+919418000001"
    with pytest.raises(AdapterError):
        normalise_phone("12")


@pytest.mark.parametrize(
    "text,intent",
    [("1", "book"), ("BOOK PLS", "book"), ("2", "list"), ("cancel", "cancel"), ("zzz", "unknown")],
)
def test_guided_flow_is_forgiving_about_how_people_reply(text, intent):
    assert parse_reply(text)["intent"] == intent


def test_the_mock_adapters_write_real_rows(client, admin_token):
    """ARCHITECTURE D4: mocks persist to the same tables so the demo shows real data."""
    auth = {"Authorization": f"Bearer {admin_token}"}
    rows = client.get("/api/v1/notifications?limit=5", headers=auth).json()
    assert rows, "run the spine scenario first — outbox should not be empty"
    assert all(r["mock"] is True for r in rows)
    assert all(r["body"] for r in rows), "an outbox row with no body shows nothing to a judge"


async def test_sms_takes_over_when_whatsapp_refuses(monkeypatch):
    """The fallback path only matters once it has actually been exercised."""
    from app.adapters import factory
    from app.services import notify

    class AlwaysFails:
        channel = Channel.WHATSAPP

        async def send(self, **_):
            return DeliveryResult(
                status=NotificationStatus.FAILED, mock=True, error="opted out (forced)"
            )

        async def health(self):
            return True

    from app.adapters.sms_mock import MockSms

    # A seeded SMS mock, because the unseeded one fails 3% of the time by design and
    # this test is about the fallback happening, not about gateway luck.
    always_works = MockSms(seed=1)
    assert factory.messaging is not None

    def pick(channel):
        return AlwaysFails() if channel == Channel.WHATSAPP else always_works

    monkeypatch.setattr(notify, "messaging", pick)

    class FakePatient:
        id = "00000000-0000-0000-0000-000000000000"
        phone = "9418000001"

    class FakeDb:
        def __init__(self):
            self.added = []

        def add(self, row):
            self.added.append(row)

        async def flush(self):
            return None

    written = await notify._fan_out(FakeDb(), None, FakePatient(), "booked", PARAMS)
    assert [n.channel for n in written] == [Channel.WHATSAPP, Channel.SMS]
    assert written[0].status == NotificationStatus.FAILED
    assert written[1].status == NotificationStatus.SENT, "SMS should have picked it up"

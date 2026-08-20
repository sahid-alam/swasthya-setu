"""One contract, every messaging adapter — mock always, real only when credentials
exist (integration-adapter SKILL.md step 5).

The point is that upstream code cannot tell them apart: same return type, same status
vocabulary, failure reported rather than raised. A mock that behaves better than the
real thing is how a demo passes and a deployment does not.
"""

import os

import pytest

from app.adapters.base import AdapterError, DeliveryResult
from app.adapters.email_mock import MockEmail
from app.adapters.sms_mock import MockSms
from app.adapters.whatsapp_mock import MockWhatsApp
from app.models import NotificationStatus

OK = (NotificationStatus.SENT, NotificationStatus.DELIVERED, NotificationStatus.FAILED)

CASES = [
    pytest.param(MockSms, "9418000001", id="sms-mock"),
    pytest.param(MockWhatsApp, "9418000001", id="whatsapp-mock"),
    pytest.param(MockEmail, "someone@example.test", id="email-mock"),
]

if os.environ.get("WHATSAPP_TOKEN") and os.environ.get("WHATSAPP_PHONE_NUMBER_ID"):
    from app.adapters.whatsapp_real import CloudApiWhatsApp

    CASES.append(
        pytest.param(CloudApiWhatsApp, os.environ["WHATSAPP_TEST_RECIPIENT"], id="whatsapp-real")
    )

if os.environ.get("SMTP_HOST") and os.environ.get("SMTP_USERNAME"):
    from app.adapters.email_smtp import SmtpEmail

    CASES.append(pytest.param(SmtpEmail, os.environ["SMTP_USERNAME"], id="email-real"))


@pytest.mark.parametrize("adapter_cls, to", CASES)
def test_an_adapter_returns_a_result_rather_than_raising(client, adapter_cls, to):
    async def _send():
        return await adapter_cls().send(
            to=to, template="otp", params={"code": "123456", "minutes": 5, "language": "EN"}
        )

    result = client.portal.call(_send)
    assert isinstance(result, DeliveryResult)
    assert result.status in OK
    assert result.payload.get("to")
    if result.status is NotificationStatus.FAILED:
        assert result.error, "a failure must say why — the outbox is judge-facing"


@pytest.mark.parametrize("adapter_cls, to", CASES)
def test_health_never_raises(client, adapter_cls, to):
    assert isinstance(client.portal.call(adapter_cls().health), bool)


# --------------------------------------------- Cloud API payload shape (no network)


def _cloud_api(monkeypatch, templates: str = ""):
    from app.adapters import whatsapp_real
    from app.config import get_settings

    s = get_settings()
    monkeypatch.setattr(s, "whatsapp_token", "test-token", raising=False)
    monkeypatch.setattr(s, "whatsapp_phone_number_id", "1234567890", raising=False)
    monkeypatch.setattr(s, "whatsapp_templates", templates, raising=False)
    return whatsapp_real.CloudApiWhatsApp()


def test_without_an_approved_template_the_message_goes_as_text(monkeypatch):
    """Which Meta only accepts inside the 24-hour window — correct, and the failure
    outside it is reported with Meta's own reason rather than guessed at."""
    payload = _cloud_api(monkeypatch)._payload(
        "+919418000001", "otp", {"code": "123456", "minutes": 5, "language": "EN"}
    )
    assert payload["type"] == "text"
    assert "123456" in payload["text"]["body"]


def test_a_configured_template_is_sent_as_a_template_with_ordered_parameters(monkeypatch):
    adapter = _cloud_api(
        monkeypatch, '{"otp": {"name": "setu_otp", "lang": "en", "params": ["code", "minutes"]}}'
    )
    payload = adapter._payload("+919418000001", "otp", {"code": "123456", "minutes": 5})

    assert payload["type"] == "template"
    assert payload["template"]["name"] == "setu_otp"
    assert [p["text"] for p in payload["template"]["components"][0]["parameters"]] == [
        "123456",
        "5",
    ]


def test_malformed_template_config_fails_loudly_at_construction(monkeypatch):
    with pytest.raises(AdapterError):
        _cloud_api(monkeypatch, "{not json")


def test_missing_credentials_fail_loudly_rather_than_sending_nowhere(monkeypatch):
    from app.adapters import whatsapp_real
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "whatsapp_token", "", raising=False)
    with pytest.raises(AdapterError):
        whatsapp_real.CloudApiWhatsApp()

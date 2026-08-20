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
from app.adapters.telegram_mock import MockTelegram
from app.adapters.whatsapp_mock import MockWhatsApp
from app.models import NotificationStatus

OK = (NotificationStatus.SENT, NotificationStatus.DELIVERED, NotificationStatus.FAILED)

CASES = [
    pytest.param(MockSms, "9418000001", id="sms-mock"),
    pytest.param(MockWhatsApp, "9418000001", id="whatsapp-mock"),
    pytest.param(MockEmail, "someone@example.test", id="email-mock"),
    pytest.param(MockTelegram, "987654321", id="telegram-mock"),
]

if os.environ.get("TELEGRAM_BOT_TOKEN") and os.environ.get("TELEGRAM_TEST_CHAT_ID"):
    from app.adapters.telegram_real import TelegramBot

    CASES.append(pytest.param(TelegramBot, os.environ["TELEGRAM_TEST_CHAT_ID"], id="telegram-real"))

if os.environ.get("SMS_GATEWAY_URL") and os.environ.get("SMS_TEST_RECIPIENT"):
    from app.adapters.sms_real import GatewaySms

    CASES.append(pytest.param(GatewaySms, os.environ["SMS_TEST_RECIPIENT"], id="sms-real"))

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


# ------------------------------------ Cloud API behaviour against a stubbed Graph API
#
# The credentials are not here yet, but the retry policy and the 24-hour rejection are
# ours, not Meta's — so they are testable without a real number.


def _stub(monkeypatch, responses):
    """Serve `responses` in order to the adapter's httpx client, counting calls."""
    import httpx

    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return responses[min(calls["n"] - 1, len(responses) - 1)]

    real_client = httpx.AsyncClient

    def client(*args, **kwargs):
        return real_client(*args, **{**kwargs, "transport": httpx.MockTransport(handler)})

    monkeypatch.setattr(httpx, "AsyncClient", client)
    return calls


def test_a_5xx_is_retried_and_can_still_succeed(client, monkeypatch):
    import httpx

    calls = _stub(
        monkeypatch,
        [
            httpx.Response(500, text="upstream sad"),
            httpx.Response(200, json={"messages": [{"id": "wamid.TEST"}]}),
        ],
    )
    adapter = _cloud_api(monkeypatch)
    monkeypatch.setattr("asyncio.sleep", _no_wait)

    result = client.portal.call(
        lambda: adapter.send(to="9418000001", template="otp", params={"code": "1", "minutes": 5})
    )
    assert result.status is NotificationStatus.SENT
    assert result.provider_ref == "wamid.TEST"
    assert calls["n"] == 2


def test_being_outside_the_24_hour_window_is_not_retried_and_says_what_to_do(client, monkeypatch):
    """131047 means 'send a template instead'. Retrying it just spends the rate limit,
    and an error that does not name the fix is an error someone re-debugs at 3am."""
    import httpx

    calls = _stub(
        monkeypatch,
        [
            httpx.Response(
                400,
                json={"error": {"code": 131047, "message": "Re-engagement message"}},
                headers={"content-type": "application/json"},
            )
        ],
    )
    adapter = _cloud_api(monkeypatch)

    result = client.portal.call(
        lambda: adapter.send(to="9418000001", template="otp", params={"code": "1", "minutes": 5})
    )
    assert result.status is NotificationStatus.FAILED
    assert calls["n"] == 1
    assert "WHATSAPP_TEMPLATES" in result.error and "otp" in result.error


async def _no_wait(_seconds):
    return None

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

# Live cases send real messages to real people, so they are opt-in per run rather than
# "on because credentials exist". SMS has no live case at all: it costs money and rides
# one handset (CLAUDE.md §Conventions). Verify that one by hand, deliberately.
LIVE = os.environ.get("LIVE_CONTRACT_TESTS") == "1"


CASES = [
    pytest.param(MockSms, "9418000001", id="sms-mock"),
    pytest.param(MockWhatsApp, "9418000001", id="whatsapp-mock"),
    pytest.param(MockEmail, "someone@example.test", id="email-mock"),
    pytest.param(MockTelegram, "987654321", id="telegram-mock"),
]

if LIVE and os.environ.get("TELEGRAM_BOT_TOKEN") and os.environ.get("TELEGRAM_TEST_CHAT_ID"):
    from app.adapters.telegram_real import TelegramBot

    CASES.append(pytest.param(TelegramBot, os.environ["TELEGRAM_TEST_CHAT_ID"], id="telegram-real"))


if LIVE and os.environ.get("WHATSAPP_TOKEN") and os.environ.get("WHATSAPP_PHONE_NUMBER_ID"):
    from app.adapters.whatsapp_real import CloudApiWhatsApp

    CASES.append(
        pytest.param(CloudApiWhatsApp, os.environ["WHATSAPP_TEST_RECIPIENT"], id="whatsapp-real")
    )

if LIVE and os.environ.get("SMTP_HOST") and os.environ.get("SMTP_USERNAME"):
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


# ------------------------------------------------------- the real-SMS rate ceiling
#
# There is no live SMS case above and there never will be. What is testable without
# sending anything is the guard that stands in front of the gateway.


def test_the_real_sms_ceiling_is_a_hard_stop(client, monkeypatch):
    """30/day and 5/minute, counted in Redis. A replan that moves forty patients must
    not be able to put forty messages through a phone in someone's pocket."""
    from datetime import UTC, datetime

    from app import events
    from app.adapters import sms_fence

    minute = datetime(2031, 4, 5, 6, 7, tzinfo=UTC)

    async def _drain():
        for key, _, _ in sms_fence._limit_keys(minute):
            await events.client().delete(key)

    client.portal.call(_drain)
    try:
        allowed = [
            client.portal.call(lambda: sms_fence.over_limit(minute))
            for _ in range(sms_fence.MAX_PER_MINUTE)
        ]
        assert allowed == [None] * sms_fence.MAX_PER_MINUTE

        refused = client.portal.call(lambda: sms_fence.over_limit(minute))
        assert refused and "per minute" in refused
    finally:
        client.portal.call(_drain)


def test_over_the_ceiling_is_a_failed_row_not_an_exception(client, monkeypatch):
    """The caller degrades: a refused send is recorded in the outbox with the reason,
    so the demo shows why nothing arrived instead of appearing to have sent."""
    from app.adapters import sms_real
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "sms_gateway_url", "http://127.0.0.1:9", raising=False)

    async def _always_full(_now=None):
        return "real-SMS rate limit reached (test); not sent"

    # patched where it is used, not where it is defined
    monkeypatch.setattr(sms_real, "over_limit", _always_full)
    result = client.portal.call(
        lambda: sms_real.GatewaySms().send(
            to="9418000001", template="otp", params={"code": "1", "minutes": 5}
        )
    )
    assert result.status is NotificationStatus.FAILED
    assert "rate limit" in result.error


def test_the_cloud_relay_answers_200_even_when_it_refused(client, monkeypatch):
    """Traccar's relay returns 200 and puts FCM's verdict in the body. Trusting the
    status code would record a delivery that never left Google's servers — which is
    exactly what a stale Cloud token looks like."""
    _no_fence(monkeypatch)
    import httpx

    from app.adapters import sms_real
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "sms_cloud_token", "stale-token", raising=False)
    _stub(
        monkeypatch,
        [
            httpx.Response(
                200,
                json={
                    "successCount": 0,
                    "failureCount": 1,
                    "responses": [
                        {
                            "success": False,
                            "error": {
                                "code": "messaging/registration-token-not-registered",
                                "message": "NotRegistered",
                            },
                        }
                    ],
                },
            )
        ],
    )

    result = client.portal.call(
        lambda: sms_real.GatewaySms().send(
            to="9418000001", template="otp", params={"code": "1", "minutes": 5}
        )
    )
    assert result.status is NotificationStatus.FAILED
    assert "cloud relay refused" in result.error
    assert "SMS_CLOUD_TOKEN" in result.error, "the error must name the fix"


def test_the_html_email_cannot_carry_someone_elses_markup():
    """Patients type their own names at Telegram self-registration, and this document
    is sent over our name into a third party's inbox. Nothing interpolated into it may
    be able to close a tag."""
    from app.adapters.email_smtp import as_html

    nasty = 'Asha <script>alert(1)</script> & <a href="http://evil">click</a>'
    html = as_html(nasty, f"Confirmed with Dr {nasty}", "booked", {}, "EN")

    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert 'href="http://evil"' not in html
    assert "&amp;" in html, "an ampersand in a name must not start an entity"
    # and the layout's own markup still has to survive
    assert "<table" in html and "</html>" in html


def test_a_code_is_escaped_but_still_readable():
    from app.adapters.email_smtp import as_html

    html = as_html("Your code", "your login code is 123456", "otp", {"code": "123456"}, "EN")
    assert ">123456<" in html, "the six digits still render as digits"


# ------------------------------------------------------------------ 2Factor (OTP only)


def _no_fence(monkeypatch):
    """Take the daily ceiling out of the way.

    These tests exercise the live adapters against a stubbed HTTP layer, but the fence
    is real and counts in Redis — so without this a day's testing spends the 30-per-day
    budget and the suite starts failing by the calendar rather than by the code. The
    fence has its own test above; here it is noise.
    """

    async def _clear(_now=None):
        return None

    for module in ("sms_real", "sms_2factor"):
        import importlib

        monkeypatch.setattr(importlib.import_module(f"app.adapters.{module}"), "over_limit", _clear)


def _two_factor(monkeypatch, route="VOICE"):
    from app.adapters import sms_2factor
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "twofactor_api_key", "test-key", raising=False)
    return sms_2factor.TwoFactorSms(route=route)


def test_2factor_carries_an_otp_and_nothing_else(monkeypatch):
    """It delivers digits down a phone line. A booking confirmation is a sentence, and
    reading one out as a robocall is not a feature — those go by Telegram or email."""
    adapter = _two_factor(monkeypatch)
    assert adapter.handles("otp") is True
    assert adapter.handles("booked") is False
    assert adapter.handles("rescheduled") is False


def test_the_fan_out_skips_an_otp_only_route_instead_of_failing_it(client, monkeypatch):
    """Skipped, not FAILED: a FAILED row reads as 'we tried and could not reach them'."""
    from app.adapters.base import MessagingAdapter
    from app.models import Channel
    from app.services import notify

    class OtpOnly(MessagingAdapter):
        channel = Channel.SMS

        def handles(self, template):
            return template == "otp"

        async def send(self, **_):
            raise AssertionError("must never be asked to send a booking confirmation")

        async def health(self):
            return True

    monkeypatch.setattr(notify, "messaging", lambda channel: OtpOnly())

    class FakePatient:
        id = "00000000-0000-0000-0000-000000000000"
        phone = "9418000001"
        email = None
        telegram_chat_id = None

    class FakeDb:
        def add(self, row):
            pass

        async def flush(self):
            return None

    written = client.portal.call(
        lambda: notify._fan_out(
            FakeDb(), None, FakePatient(), "booked", {"language": "EN"}, [Channel.SMS]
        )
    )
    assert written == [], "no attempt, no row — it was never a way to send this"


def test_2factor_builds_the_documented_url(client, monkeypatch):
    """GET /{key}/{route}/{phone}/{otp} — and the number goes bare, no +91."""
    _no_fence(monkeypatch)
    import httpx

    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        return httpx.Response(200, json={"Status": "Success", "Details": "abc-123"})

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda *a, **k: real_client(*a, **{**k, "transport": httpx.MockTransport(handler)}),
    )

    adapter = _two_factor(monkeypatch)
    result = client.portal.call(
        lambda: adapter.send(to="+91 94180 00001", template="otp", params={"code": "123456"})
    )
    assert result.status is NotificationStatus.SENT
    assert result.provider_ref == "abc-123"
    assert seen["url"].endswith("/test-key/VOICE/9418000001/123456")


def test_2factor_answers_200_when_it_refused(client, monkeypatch):
    """Status lives in the body, not the status code — a bad key still returns 200."""
    _no_fence(monkeypatch)
    import httpx

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda *a, **k: real_client(
            *a,
            **{
                **k,
                "transport": httpx.MockTransport(
                    lambda r: httpx.Response(
                        200, json={"Status": "Error", "Details": "Invalid API Key"}
                    )
                ),
            },
        ),
    )
    adapter = _two_factor(monkeypatch)
    result = client.portal.call(
        lambda: adapter.send(to="9418000001", template="otp", params={"code": "123456"})
    )
    assert result.status is NotificationStatus.FAILED
    assert "Invalid API Key" in result.error


def test_2factor_without_a_key_fails_loudly(monkeypatch):
    from app.adapters import sms_2factor
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "twofactor_api_key", "", raising=False)
    with pytest.raises(AdapterError):
        sms_2factor.TwoFactorSms()


def test_the_outbox_row_describes_the_call_without_repeating_the_code(client, monkeypatch):
    """A voice row has no message to show, so it needs a description — but writing the
    digits into a table any staff login can read would undo a one-time code."""
    _no_fence(monkeypatch)
    import httpx

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda *a, **k: real_client(
            *a,
            **{
                **k,
                "transport": httpx.MockTransport(
                    lambda r: httpx.Response(200, json={"Status": "Success", "Details": "ref"})
                ),
            },
        ),
    )
    adapter = _two_factor(monkeypatch)
    result = client.portal.call(
        lambda: adapter.send(to="9418000001", template="otp", params={"code": "424242"})
    )
    assert "Voice call placed" in result.payload["body"]
    assert "424242" not in result.payload["body"]
    assert "424242" not in str(result.payload)

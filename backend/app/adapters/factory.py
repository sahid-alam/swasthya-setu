"""Adapter selection. Default is always mock — the demo must never depend on vendor
uptime, venue internet, or account approval (Iron Rule 1)."""

from __future__ import annotations

from functools import cache

from app.adapters.base import MessagingAdapter, TelephonyAdapter
from app.adapters.email_mock import MockEmail
from app.adapters.ivr_mock import MockExotel
from app.adapters.sms_mock import MockSms
from app.adapters.telegram_mock import MockTelegram
from app.adapters.whatsapp_mock import MockWhatsApp
from app.config import get_settings
from app.models import Channel


@cache
def messaging(channel: Channel) -> MessagingAdapter:
    settings = get_settings()
    if channel == Channel.SMS:
        if mock_mode(Channel.SMS):
            return MockSms()
        if settings.sms_provider.startswith("2factor"):
            from app.adapters.sms_2factor import TwoFactorSms  # imported only when used

            route = "SMS" if settings.sms_provider == "2factor-sms" else "VOICE"
            return TwoFactorSms(route=route)
        from app.adapters.sms_real import GatewaySms

        return GatewaySms()
    if channel == Channel.EMAIL:
        if settings.email_mock_mode:
            return MockEmail()
        from app.adapters.email_smtp import SmtpEmail  # imported only when actually used

        return SmtpEmail()
    if channel == Channel.TELEGRAM:
        if settings.telegram_mock_mode:
            return MockTelegram()
        from app.adapters.telegram_real import TelegramBot  # imported only when used

        return TelegramBot()
    if channel == Channel.WHATSAPP:
        if settings.whatsapp_mock_mode:
            return MockWhatsApp()
        from app.adapters.whatsapp_real import CloudApiWhatsApp

        return CloudApiWhatsApp()
    raise ValueError(f"no messaging adapter for {channel}")


def telephony() -> TelephonyAdapter:
    """Not cached: it holds no connection, and a cached instance would outlive a test
    that flips TELEPHONY_MOCK_MODE."""
    if get_settings().telephony_mock_mode:
        return MockExotel()
    from app.adapters.ivr_real import ExotelTelephony  # imported only when actually used

    return ExotelTelephony()


def mock_mode(channel: Channel) -> bool:
    settings = get_settings()
    return {
        # Either switch can force the mock, and neither can be overridden by the other:
        # this is the channel that costs money and rings a real phone.
        Channel.SMS: settings.sms_mock_mode or settings.sms_provider == "mock",
        Channel.WHATSAPP: settings.whatsapp_mock_mode,
        Channel.IVR: settings.telephony_mock_mode,
        Channel.EMAIL: settings.email_mock_mode,
        Channel.TELEGRAM: settings.telegram_mock_mode,
    }.get(channel, True)

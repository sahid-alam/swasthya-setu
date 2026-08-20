"""Adapter selection. Default is always mock — the demo must never depend on vendor
uptime, venue internet, or account approval (Iron Rule 1)."""

from __future__ import annotations

from functools import cache

from app.adapters.base import MessagingAdapter, TelephonyAdapter
from app.adapters.ivr_mock import MockExotel
from app.adapters.sms_mock import MockSms
from app.adapters.whatsapp_mock import MockWhatsApp
from app.config import get_settings
from app.models import Channel


@cache
def messaging(channel: Channel) -> MessagingAdapter:
    settings = get_settings()
    if channel == Channel.SMS:
        if settings.sms_mock_mode:
            return MockSms()
        from app.adapters.sms_real import Msg91Sms  # imported only when actually used

        return Msg91Sms()
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
        Channel.SMS: settings.sms_mock_mode,
        Channel.WHATSAPP: settings.whatsapp_mock_mode,
        Channel.IVR: settings.telephony_mock_mode,
    }.get(channel, True)

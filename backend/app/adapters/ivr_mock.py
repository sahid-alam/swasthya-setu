"""Mock Exotel telephony. Mock means no phone line, not a stub: the payload this
parses is the provider's shape, so the router never learns a vendor field name and
`simulators/ivr_call.py` is indistinguishable from a real inbound call.

There is no `ivr_real.py` yet — the skill says real second, and only once credentials
exist (`EXOTEL_SID` / `EXOTEL_TOKEN` in `.env.example`).
"""

from __future__ import annotations

from app.adapters.base import AdapterError, CallTurn, TelephonyAdapter, normalise_phone
from app.models import Channel


class MockExotel(TelephonyAdapter):
    channel = Channel.IVR

    def parse_call(self, payload: dict) -> CallTurn:
        call_id = str(payload.get("CallSid") or "").strip()
        caller = str(payload.get("From") or payload.get("CallFrom") or "").strip()
        if not call_id or not caller:
            raise AdapterError("call webhook has no CallSid/From")

        # Keypresses arrive as text, and a gather ends on the terminator the caller
        # pressed — so "1#" and a quoted "1" are both the digit 1. Anything that is
        # not a digit after that is the same as silence: nothing was pressed.
        raw = str(payload.get("Digits") or "").strip().strip('"').rstrip("#")
        return CallTurn(
            call_id=call_id,
            from_phone=normalise_phone(caller),
            digits=raw if raw.isdigit() else None,
        )

    async def health(self) -> bool:
        return True

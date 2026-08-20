"""A feature phone calling the hospital — PRD §M3 accept #1.

    python simulators/ivr_call.py 9823872276 1 1 1     # scripted: press 1, 1, 1
    python simulators/ivr_call.py 9823872276           # interactive: type digits

Posts the payload shape a telephony provider posts (CallSid / From / Digits) to the
same public webhook Exotel would, and prints what the caller hears. Like every other
simulator this is an external HTTP client — it never touches the database.
"""

from __future__ import annotations

import argparse
import sys
import uuid

from client import Setu

WEBHOOK = "/api/v1/channels/ivr/webhook"


def press(api: Setu, call_sid: str, caller: str, digits: str | None) -> dict:
    """One webhook. `digits=None` is the call connecting, before any keypress."""
    payload = {"CallSid": call_sid, "From": caller, "Direction": "incoming"}
    if digits is not None:
        payload["Digits"] = f'"{digits}"'  # providers hand keypresses back as text
    r = api.http.post(WEBHOOK, json=payload)
    r.raise_for_status()
    return r.json()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("phone", help="the caller's number — must be a patient on file")
    ap.add_argument("digits", nargs="*", help="keypresses to send, in order")
    args = ap.parse_args()

    api = Setu()
    call_sid = f"CA{uuid.uuid4().hex[:16]}"
    print(f"☎  dialling from {args.phone} …  (call {call_sid})\n")

    queued = list(args.digits)
    pressed: str | None = None
    while True:
        reply = press(api, call_sid, args.phone, pressed)
        print(f"   ♫ {reply['say']}\n")
        if reply["hangup"]:
            if reply.get("booked_appointment_id"):
                print(f"   ✓ appointment {reply['booked_appointment_id']}")
            print("☎  call ended")
            api.close()
            return 0

        if queued:
            pressed = queued.pop(0)
            print(f"   … presses {pressed}")
        else:
            try:
                pressed = input("   press a digit (enter = say nothing): ").strip() or None
            except (EOFError, KeyboardInterrupt):
                print("\n☎  caller hung up")
                api.close()
                return 1


if __name__ == "__main__":
    sys.exit(main())

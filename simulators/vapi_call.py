"""A voice agent booking an appointment — with no voice, and no internet.

    python simulators/vapi_call.py 9823872276 "General Medicine" 1

Posts the exact tool-call envelope Vapi posts, in the order a real conversation would
produce it: identify the caller, offer times, take a choice. That makes the voice
booking path demoable on a laptop with the wifi off — the speech is the part that needs
Vapi, and the speech is not the part that books anything.

Needs SETU_TOOL_SECRET to match VAPI_TOOL_SECRET on the server (the tool endpoint is
public by necessity, so it is authenticated by a shared secret rather than our JWT).
"""

from __future__ import annotations

import argparse
import os
import sys
import uuid

import httpx

API = os.environ.get("SETU_API", "http://localhost:8000")
SECRET = os.environ.get("SETU_TOOL_SECRET", "")
TOOLS = "/api/v1/channels/vapi/tools"


def call_tool(http: httpx.Client, call_id: str, name: str, arguments: dict) -> str:
    payload = {
        "message": {
            "type": "tool-calls",
            "call": {"id": call_id},
            "toolCallList": [
                {"id": f"tc_{uuid.uuid4().hex[:8]}", "name": name, "arguments": arguments}
            ],
        }
    }
    r = http.post(TOOLS, json=payload, headers={"X-Setu-Tool-Secret": SECRET})
    r.raise_for_status()
    return r.json()["results"][0]["result"]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("phone", help="the caller's number — must be a patient on file")
    ap.add_argument("department", help='e.g. "General Medicine"')
    ap.add_argument("option", nargs="?", type=int, default=1, help="which time to take")
    args = ap.parse_args()

    if not SECRET:
        print("set SETU_TOOL_SECRET to the server's VAPI_TOOL_SECRET", file=sys.stderr)
        return 2

    call_id = f"vapi_{uuid.uuid4().hex[:12]}"
    print(f"🎙  voice call {call_id}\n")
    with httpx.Client(base_url=API, timeout=15.0) as http:
        for name, arguments in (
            ("find_patient", {"phone": args.phone}),
            ("find_slots", {"department": args.department}),
            ("book_slot", {"option": args.option}),
        ):
            print(f"   → {name}({arguments})")
            print(f"   ← {call_tool(http, call_id, name, arguments)}\n")
    print("🎙  call ended")
    return 0


if __name__ == "__main__":
    sys.exit(main())

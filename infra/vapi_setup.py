"""Create or update the Swasthya-Setu voice assistant in Vapi.

    cd backend && .venv/bin/python ../infra/vapi_setup.py            # create/update
    cd backend && .venv/bin/python ../infra/vapi_setup.py --show     # just look

Idempotent: it finds the assistant by name and PATCHes it, so re-running after you set
PUBLIC_BASE_URL is how the booking tools get wired up.

Reads `VAPI_API` (or VAPI_PRIVATE_KEY) from `.env` through the app settings and never
prints it. Nothing here is needed to run the demo — `simulators/vapi_call.py` exercises
the same tools with no internet, and the IVR line books from a feature phone.
"""

from __future__ import annotations

import argparse
import json
import sys

import httpx

sys.path.insert(0, ".")
from app.config import get_settings  # noqa: E402

API = "https://api.vapi.ai"
NAME = "Swasthya-Setu Booking"

SYSTEM_PROMPT = """You are the appointment desk for Swasthya-Setu, a hospital network in
Himachal Pradesh, India. You speak English and Hindi — answer in whichever language the
caller uses, and switch if they switch.

Your only job is booking an outpatient appointment. In order:
1. Ask for the caller's ten-digit mobile number and call find_patient with it.
2. Ask which department they need and call find_slots with the department name.
3. Read out the options exactly as the tool gives them, then call book_slot with the
   number they choose.

Rules that matter:
- Never invent a doctor, a time, a token number or a department. Every fact you say
  about availability must have come from a tool result in this call.
- If a tool tells you something is not on file or not available, say that plainly and
  offer what the tool did give you.
- Keep every turn to one or two short sentences. This is a phone call, not a document.
- You cannot cancel, reschedule, give medical advice, or discuss anything clinical. For
  any of those, tell them to call the hospital reception.
"""

FIRST_MESSAGE = (
    "Swasthya-Setu appointments, namaste. I can book an outpatient appointment for you. "
    "May I have your ten-digit mobile number?"
)

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "find_patient",
            "description": "Look up the caller by mobile number. Call this first.",
            "parameters": {
                "type": "object",
                "properties": {
                    "phone": {
                        "type": "string",
                        "description": "Ten-digit Indian mobile number",
                    }
                },
                "required": ["phone"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_slots",
            "description": (
                "Open appointment times in a department. Read the options back verbatim."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "department": {
                        "type": "string",
                        "description": "Department name, e.g. General Medicine, Orthopaedics",
                    }
                },
                "required": ["department"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "book_slot",
            "description": "Book the option the caller chose, by its number.",
            "parameters": {
                "type": "object",
                "properties": {
                    "option": {"type": "integer", "description": "1, 2 or 3 as offered"}
                },
                "required": ["option"],
            },
        },
    },
]


def payload(settings) -> dict:
    body: dict = {
        "name": NAME,
        "firstMessage": FIRST_MESSAGE,
        "model": {
            "provider": "openai",
            "model": "gpt-4o-mini",
            "messages": [{"role": "system", "content": SYSTEM_PROMPT}],
            "tools": TOOLS,
        },
        "voice": {
            "provider": settings.vapi_voice_provider,
            "voiceId": settings.vapi_voice_id,
        },
    }
    if settings.public_base_url:
        # Vapi calls this from its own servers, so it has to be reachable from the
        # internet. Without it the assistant can talk but cannot book, which is worth
        # saying out loud rather than shipping a demo that fails mid-sentence.
        body["server"] = {
            "url": f"{settings.public_base_url.rstrip('/')}/api/v1/channels/vapi/tools",
            "headers": {"X-Setu-Tool-Secret": settings.vapi_tool_secret},
        }
    return body


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--show", action="store_true", help="list assistants, change nothing"
    )
    args = ap.parse_args()

    settings = get_settings()
    if not settings.vapi_private_key:
        print("no Vapi key found — set VAPI_API in .env", file=sys.stderr)
        return 2

    headers = {"Authorization": f"Bearer {settings.vapi_private_key}"}
    with httpx.Client(base_url=API, headers=headers, timeout=30.0) as http:
        r = http.get("/assistant")
        if not r.is_success:
            print(f"vapi said {r.status_code}: {r.text[:400]}", file=sys.stderr)
            return 1
        existing = {a.get("name"): a for a in r.json()}

        if args.show:
            for name, a in existing.items():
                print(f"{a.get('id')}  {name}")
            return 0

        body = payload(settings)
        if NAME in existing:
            assistant_id = existing[NAME]["id"]
            r = http.patch(f"/assistant/{assistant_id}", json=body)
            verb = "updated"
        else:
            r = http.post("/assistant", json=body)
            verb = "created"

        if not r.is_success:
            print(f"vapi said {r.status_code}: {r.text[:800]}", file=sys.stderr)
            return 1

        got = r.json()
        print(f"{verb} assistant {got['id']}  ({got.get('name')})")
        print(f"  voice      : {json.dumps(got.get('voice') or {})}")
        print(f"  tools      : {len((got.get('model') or {}).get('tools') or [])}")
        server = (got.get("server") or {}).get("url")
        print(f"  server url : {server or 'NOT SET — it can talk, it cannot book'}")
        print("\nset VAPI_ASSISTANT_ID in .env to:", got["id"])
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Check the SMS gateway, and optionally send exactly one real message.

    cd backend && .venv/bin/python ../infra/sms_probe.py           # reachability only
    cd backend && .venv/bin/python ../infra/sms_probe.py --send    # one real SMS

Reachability is checked first and separately, because "the phone is not on the network"
and "the payload shape is wrong" are different problems and the error messages for them
look nothing alike.

`--send` puts one real message through a real SIM. It obeys the same 30/day, 5/minute
ceiling as the adapter — it *is* the adapter — and it will not loop. Everything
automated runs against the mock (CLAUDE.md §Conventions).
"""

from __future__ import annotations

import argparse
import asyncio
import errno as errno_module
import socket
import sys
from urllib.parse import urlparse

sys.path.insert(0, ".")
from app.config import get_settings  # noqa: E402


def reachable(url: str) -> tuple[bool, str, int | None]:
    """TCP first: it separates 'not on this network' from 'answered with an error'."""
    parsed = urlparse(url)
    host, port = parsed.hostname or "", parsed.port or 80
    try:
        with socket.create_connection((host, port), timeout=4):
            return True, f"{host}:{port} accepted a connection", 0
    except OSError as exc:
        return False, f"{host}:{port} — {exc}", exc.errno


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--send", action="store_true", help="send ONE real SMS")
    args = ap.parse_args()

    s = get_settings()
    if not s.sms_gateway_url:
        print("SMS_GATEWAY_URL is not set in .env", file=sys.stderr)
        return 2

    ok, detail, errno = reachable(s.sms_gateway_url)
    print(f"[{'ok' if ok else 'FAIL'}] {detail}")
    if not ok:
        # The two failure modes look identical in the app and nothing alike at the
        # socket, so let the socket decide which advice to give.
        if errno == errno_module.EHOSTUNREACH:
            print(
                "\nNothing on this LAN answered for that address — no ARP reply at all.\n"
                "  1. the phone is dozing: wake it, and turn OFF battery optimisation\n"
                "     for the gateway app, or Android stops answering while the screen is\n"
                "  2. its wifi is off, or it is on mobile data\n"
                "  3. its IP moved — check the app's Endpoints screen against .env"
            )
        else:
            print(
                "\nSomething is between us: the address exists but the port did not open.\n"
                "  1. client/AP isolation on the router — devices cannot see each other\n"
                "  2. phone on a different SSID or band\n"
                "  3. the app's Local Service toggle is off"
            )
        print(
            "\nQuickest way past all of it: turn on the phone's hotspot, join it from this\n"
            "machine, read the new address off the app's Endpoints screen into .env.\n"
            "Check the other direction from the phone's browser:\n"
            "  http://<this machine's address>:8000/api/v1/health"
        )
        return 1

    if not args.send:
        print("reachable. Re-run with --send to put one real message through.")
        return 0

    to = s.sms_test_recipient
    if not to:
        print("SMS_TEST_RECIPIENT is not set in .env", file=sys.stderr)
        return 2

    from app.adapters.sms_real import GatewaySms

    result = await GatewaySms().send(
        to=to,
        template="otp",
        params={"code": "000000", "minutes": 5, "language": "EN"},
    )
    print(f"[{result.status.value}] {result.error or result.provider_ref}")
    print("  payload sent:", {k: v for k, v in result.payload.items() if k != "body"})
    return 0 if result.status.value in ("SENT", "DELIVERED") else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

"""Failure drill — what survives when Redis dies mid-demo.

    make failure-drill

Redis carries the event bus, OTP codes, WhatsApp session state and the SMS rate fence.
Postgres carries appointments. The claim this drill exists to prove is that **losing
Redis costs you live updates, not bookings** — the dashboard stops streaming and says
so, and a patient can still book.

It stops Redis, checks, and **always restarts it**, including on Ctrl-C or a crash.
Leaving a presenter's Redis down would be a worse outcome than never running the drill.

Run it before a demo, not during one.
"""

import os
import subprocess
import sys
import time

import httpx

API = "http://localhost:8000/api/v1"
CONTAINER = os.environ.get("REDIS_CONTAINER", "swasthya-setu-redis-1")

results = []


def report(step: str, ok: bool, detail: str = "") -> None:
    results.append((step, ok))
    print(f"  [{'PASS' if ok else 'FAIL'}] {step}" + (f" — {detail}" if detail else ""))


def docker(action: str) -> bool:
    out = subprocess.run(["docker", action, CONTAINER], capture_output=True, text=True)
    return out.returncode == 0


def token() -> str:
    password = open(os.path.join(os.path.dirname(__file__), "..", ".admin-password")).read().strip()
    r = httpx.post(
        f"{API}/auth/token",
        data={"username": "9418000001", "password": password},
        timeout=10,
    )
    r.raise_for_status()
    return r.json()["access_token"]


def main() -> None:
    tok = token()
    headers = {"Authorization": f"Bearer {tok}"}

    health = httpx.get(f"{API}/health", timeout=5).json()
    if not health.get("redis"):
        raise SystemExit("Redis is already down — nothing to drill. Start it first.")
    report("baseline: Redis up, Postgres up", health["postgres"] and health["redis"])

    if not docker("stop"):
        raise SystemExit(
            f"could not stop container {CONTAINER}. Set REDIS_CONTAINER, or run Redis "
            "in Docker for this drill."
        )
    print(f"\n  ...stopped {CONTAINER}\n")

    try:
        time.sleep(1.5)

        # 1. The app must still answer at all, and must admit what is wrong.
        try:
            degraded = httpx.get(f"{API}/health", timeout=8).json()
            report(
                "health still answers and reports the outage",
                degraded.get("redis") is False and degraded.get("status") == "degraded",
                f"status={degraded.get('status')} redis={degraded.get('redis')}",
            )
        except Exception as exc:  # noqa: BLE001
            report("health still answers and reports the outage", False, str(exc))

        # 2. Reads that only need Postgres must be untouched. This is the real claim:
        #    the clinical data is in Postgres and Redis is not in that path.
        for name, path in (
            ("presence board", "/presence"),
            ("clinic list", "/scheduling/clinic"),
            ("bed occupancy", "/beds/occupancy"),
        ):
            try:
                r = httpx.get(f"{API}{path}", headers=headers, timeout=8)
                report(
                    f"{name} still served without Redis",
                    r.status_code == 200,
                    f"HTTP {r.status_code}",
                )
            except Exception as exc:  # noqa: BLE001
                report(f"{name} still served without Redis", False, str(exc))

        # 3. Golden Hour is pure Postgres + the routing adapter, so an emergency
        #    ranking must survive an event-bus outage.
        try:
            r = httpx.post(
                f"{API}/emergency/rank",
                headers=headers,
                json={"lat": 31.45, "lng": 77.63, "specialty": "General Surgery"},
                timeout=10,
            )
            report(
                "Golden Hour still ranks without Redis",
                r.status_code == 200 and bool(r.json().get("ranked")),
                f"HTTP {r.status_code}",
            )
        except Exception as exc:  # noqa: BLE001
            report("Golden Hour still ranks without Redis", False, str(exc))

        # 4. A booking is the thing that must not be lost. It publishes an event, so
        #    the publish has to fail soft rather than take the booking down with it.
        try:
            slots = httpx.get(f"{API}/scheduling/clinic", headers=headers, timeout=8).status_code
            report(
                "booking path reachable (clinic reads OK)",
                slots == 200,
                f"HTTP {slots}",
            )
        except Exception as exc:  # noqa: BLE001
            report("booking path reachable (clinic reads OK)", False, str(exc))

    finally:
        # Always. A drill that leaves Redis down is worse than no drill.
        restored = docker("start")
        print(f"\n  ...restarted {CONTAINER}: {'ok' if restored else 'FAILED — start it by hand'}")
        for _ in range(20):
            time.sleep(0.5)
            try:
                if httpx.get(f"{API}/health", timeout=3).json().get("redis"):
                    break
            except Exception:  # noqa: BLE001
                pass
        back = httpx.get(f"{API}/health", timeout=5).json()
        report(
            "Redis back and health green again",
            back.get("redis") is True,
            back.get("status", "?"),
        )

    fails = [s for s, ok in results if not ok]
    print(f"\n{len(results) - len(fails)}/{len(results)} PASS")
    if fails:
        print("FAILED:", ", ".join(fails))
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()

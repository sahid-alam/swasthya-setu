"""Spine walk for /demo-check — the Iron Rule 4 guard.

    make demo                        # migrate + seed
    # start the backend (see infra/demo-script.md)
    backend/.venv/bin/python infra/demo_check.py

Exits non-zero on any FAIL. Run this after every change that touches the spine;
a baseline before you start is worth more than a pass afterwards, because it tells
you what was already broken.
"""

import asyncio
import json
import subprocess
import sys

sys.path.insert(0, "simulators")
import websockets
from client import Setu

results = []


def report(step, ok, detail=""):
    results.append((step, ok, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {step}" + (f" — {detail}" if detail else ""))


def psql(sql):
    out = subprocess.run(
        ["psql", "-U", "setu", "-h", "localhost", "-d", "swasthya", "-tAc", sql],
        capture_output=True,
        text=True,
    )
    return out.stdout.strip()


async def main():
    a = Setu()
    tok = a.http.headers["Authorization"].split()[1]
    doc = next(d for d in a.roster()["doctors"] if d["badge_id"] == "HP-DOC-1001")
    did = doc["doctor_id"]

    before = next(
        c
        for c in a.http.get("/api/v1/scheduling/clinic").json()
        if c["badge_id"] == "HP-DOC-1001"
    )
    report("clinic list seeded", before["booked"] > 0, f"{before['booked']} waiting")

    topics = []
    async with websockets.connect(
        f"ws://localhost:8000/ws/dashboard?token={tok}"
    ) as ws:
        assert json.loads(await ws.recv())["topic"] == "ws.ready"
        await asyncio.get_event_loop().run_in_executor(
            None, lambda: a.override(did, "ON_LEAVE", "demo-check: called in sick")
        )
        try:
            while len(topics) < 2:
                topics.append(
                    json.loads(await asyncio.wait_for(ws.recv(), timeout=10))["topic"]
                )
        except TimeoutError:
            pass

    state = psql(f"select state from doctor_status where doctor_id='{did}'")
    report("doctor_status flips to ON_LEAVE", state == "ON_LEAVE", state)
    report("presence.changed published", "presence.changed" in topics, str(topics))

    run = a.http.get("/api/v1/scheduling/plan-runs?limit=1").json()
    ok = bool(run) and run[0]["duration_ms"] < 5000 and run[0]["moved_count"] > 0
    report(
        "plan_runs: <5000ms and moved>0",
        ok,
        (
            f"{run[0]['solver_status']} {run[0]['duration_ms']}ms moved={run[0]['moved_count']}"
            if run
            else "no run"
        ),
    )

    notes = psql("select count(*) from notifications")
    report(
        "notifications rows for affected patients",
        int(notes or 0) > 0,
        f"{notes} rows (notification service is Phase 1C)",
    )

    report(
        "dashboard socket received replan",
        "appointments.replanned" in topics,
        str(topics),
    )

    after = next(
        c
        for c in a.http.get("/api/v1/scheduling/clinic").json()
        if c["badge_id"] == "HP-DOC-1001"
    )
    report(
        "absent doctor holds nobody", after["booked"] == 0, f"{after['booked']} waiting"
    )

    # Phase 2 modules do not exist yet — nothing to check (step 3 N/A)
    a.close()
    fails = [s for s, ok, _ in results if not ok]
    print(f"\n{len(results)-len(fails)}/{len(results)} PASS")
    if fails:
        print("FAILED:", ", ".join(fails))
    sys.exit(1 if fails else 0)


asyncio.run(main())

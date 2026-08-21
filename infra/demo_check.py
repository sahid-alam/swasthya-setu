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
import os
import subprocess
import sys

sys.path.insert(0, "simulators")
import websockets
from client import Setu

results = []

# Mirrors REPLAN_HORIZON_HOURS in backend/app/services/scheduling.py. Looking for a
# colleague outside the window the optimiser actually searches would pick a doctor it
# then cannot re-seat.
REPLAN_HORIZON = 24


def report(step, ok, detail=""):
    results.append((step, ok, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {step}" + (f" — {detail}" if detail else ""))


def psql(sql):
    # A local brew postgres trusts the socket; the compose one wants a password. And a
    # failure used to come back as an empty string, which surfaced much later as an
    # unpack error rather than "psql could not connect".
    out = subprocess.run(
        ["psql", "-U", "setu", "-h", "localhost", "-d", "swasthya", "-tAc", sql],
        capture_output=True,
        text=True,
        env={**os.environ, "PGPASSWORD": os.environ.get("PGPASSWORD", "setu")},
    )
    if out.returncode:
        raise SystemExit(f"psql failed: {out.stderr.strip()}")
    return out.stdout.strip()


async def main():
    a = Setu()

    # Iron Rule 4 guard, and a wallet guard: the spine moves ~40 patients, so running
    # it against a live SMS gateway would put forty real messages through someone's
    # handset. Live SMS is for deliberate manual verification only.
    mocks = a.http.get("/api/v1/health").json().get("mocks", {})
    if mocks.get("sms") is False:
        print("REFUSING: the server has SMS in live mode. Set SMS_MOCK_MODE=true.")
        sys.exit(2)
    tok = a.http.headers["Authorization"].split()[1]

    # Pick the doctor to disrupt from the data, not from a fixed badge. This run puts
    # him on leave and moves his patients away, so a second run against that same badge
    # would find nobody to move and report a broken spine when the spine is fine.
    #
    # "Worth disrupting" is two conditions, and the second one matters: he must have a
    # clinic ahead of him, AND his department must hold an available colleague with open
    # slots inside the replan horizon. Pick a doctor whose only colleague is already on
    # leave and the optimizer correctly finds nowhere to put anyone — moved=0 is then
    # the right answer to an empty department, not a failure of the spine.
    AVAILABLE = "not in ('ON_LEAVE', 'OFF_SHIFT', 'IN_SURGERY')"
    badge = psql(f"""
        select d.badge_id from doctors d
        join slots s on s.doctor_id = d.id and s.starts_at >= now()
        join appointments a on a.slot_id = s.id and a.status = 'BOOKED'
        where coalesce((select x.state::text from doctor_status x
                        where x.doctor_id = d.id), 'UNKNOWN') {AVAILABLE}
          and exists (
            select 1 from doctors d2
            join slots s2 on s2.doctor_id = d2.id
            where d2.department_id = d.department_id and d2.id <> d.id
              and s2.status = 'OPEN'
              and s2.starts_at between now() and now() + interval '{REPLAN_HORIZON} hours'
              and coalesce((select y.state::text from doctor_status y
                            where y.doctor_id = d2.id), 'UNKNOWN') {AVAILABLE}
          )
        group by d.id, d.badge_id order by count(a.id) desc limit 1
        """)
    report(
        "a doctor has a clinic the optimiser could re-seat",
        bool(badge),
        badge or "no available doctor has both a clinic and an available colleague",
    )
    if not badge:
        # Everything downstream measures a replan that cannot happen. Stop here rather
        # than reporting six misleading failures.
        a.close()
        print(f"\n{len(results)-1}/{len(results)} PASS")
        sys.exit(1)

    before = next(
        c for c in a.http.get("/api/v1/scheduling/clinic").json() if c["badge_id"] == badge
    )
    did = before["doctor_id"]
    # What to put back at the end. Without a restore, every run strands one more doctor
    # ON_LEAVE and the dataset rots a little further each time it is checked.
    was = (
        psql(
            "select ds.state from doctor_status ds join doctors d on d.id = ds.doctor_id "
            f"where d.badge_id = '{badge}'"
        )
        or "UNKNOWN"
    )

    # Only rows this run wrote. The table is not truncated between runs unless `make
    # seed` ran, so an all-time count passes on history alone — it once read
    # "747 rows for 0 patients".
    since = psql("select now()")

    # One real patient of his, captured before the replan, so the last hop of the
    # exit criterion ("patient PWA shows new slot") is checked against a patient who
    # actually held one of these appointments — not against whatever the API returns.
    victim = psql(
        "select a.patient_id, a.id, u.name from appointments a "
        "join slots s on s.id = a.slot_id "
        "join doctors d on d.id = s.doctor_id "
        "join users u on u.id = d.user_id "
        f"where d.badge_id = '{badge}' and a.status = 'BOOKED' "
        "and s.starts_at >= now() order by s.starts_at limit 1"
    ).split("|")

    topics = []
    async with websockets.connect(f"ws://localhost:8000/ws/dashboard?token={tok}") as ws:
        assert json.loads(await ws.recv())["topic"] == "ws.ready"
        await asyncio.get_event_loop().run_in_executor(
            None, lambda: a.override(did, "ON_LEAVE", "demo-check: called in sick")
        )
        try:
            while len(topics) < 2:
                topics.append(json.loads(await asyncio.wait_for(ws.recv(), timeout=10))["topic"])
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

    # Scoped to the reschedule templates and to the two messaging channels: a bare
    # count(*) would pass on booking confirmations alone. Scoped to `since` as well,
    # because without a `make seed` the table still holds every previous run's rows.
    breakdown = psql(
        "select channel || ' ' || count(*) from notifications "
        "where template in ('rescheduled', 'reschedule_pending') "
        f"and created_at >= '{since}' "
        "and channel in ('WHATSAPP', 'SMS') group by channel"
    )
    sent = sum(int(line.split()[1]) for line in breakdown.splitlines() if line)
    report(
        "mock WhatsApp/SMS outbox told every moved patient",
        sent >= before["booked"],
        f"{sent} rows for {before['booked']} patients"
        f" ({breakdown.replace(chr(10), ', ') or 'none'})",
    )

    report(
        "dashboard socket received replan",
        "appointments.replanned" in topics,
        str(topics),
    )

    after = next(
        c for c in a.http.get("/api/v1/scheduling/clinic").json() if c["badge_id"] == badge
    )
    report("absent doctor holds nobody", after["booked"] == 0, f"{after['booked']} waiting")

    # The last hop: what the patient app serves that patient now. Either she has been
    # moved to another doctor, or she is RESCHEDULE_PENDING — both are honest, and the
    # PWA renders both. Failing means she vanished from her own queue, or is still
    # being shown a doctor who is on leave. A move writes a NEW appointment row and
    # leaves the old one RESCHEDULED, so follow `rescheduled_from` rather than
    # expecting the old id to survive.
    pid, appt_id, absent_name = victim
    successor = psql(f"select id from appointments where rescheduled_from = '{appt_id}'")
    mine = a.http.get(f"/api/v1/pwa/my-queue/{pid}").json()
    entry = next((m for m in mine if m["appointment_id"] in (successor, appt_id)), None)
    report(
        "patient PWA shows the new slot (or a labelled pending one)",
        entry is not None
        and (entry["doctor_name"] != absent_name or entry["status"] == "RESCHEDULE_PENDING"),
        (
            f"{entry['status']} with {entry['doctor_name']} at {entry['scheduled_for'][11:16]}"
            if entry
            else "gone from her own queue"
        ),
    )

    # Put him back the way he was found. The check is allowed to disrupt a clinic; it is
    # not allowed to leave the dataset worse than it started, and an override that is
    # never cleared strands one more doctor ON_LEAVE on every single run.
    a.override(did, was, "demo-check: restoring state captured at start")
    print(f"  [restored] {badge} back to {was}")

    # --- the PRD's fourth and fifth beats: Golden Hour routing, then a referral ------
    # PRD §Demo requirements scripts "emergency Golden Hour routing -> referral with bed
    # reservation". Both exist now, so both get walked.

    # Rampur on NH-5, the PRD's own example location.
    ranking = a.http.post(
        "/api/v1/emergency/rank",
        json={
            "lat": 31.45,
            "lng": 77.63,
            "description": "demo-check: accident on NH-5 near Rampur",
            "specialty": "General Surgery",
            "blood_group": "O_NEG",
        },
    ).json()
    ranked = ranking.get("ranked", [])
    report(
        "Golden Hour ranks every facility under 3s",
        bool(ranked) and ranking["duration_ms"] < 3000,
        f"{len(ranked)} facilities in {ranking.get('duration_ms', '?')}ms",
    )
    # The acceptance criterion is the reasoning, not the order.
    report(
        "every ranked facility explains itself",
        bool(ranked) and all(r["why"] for r in ranked),
        (f"top: {ranked[0]['hospital']} — {ranked[0]['why'][0]}" if ranked else "nothing ranked"),
    )

    viable = [r for r in ranked if r["viable"]]
    if viable:
        destination = viable[0]
        # Refer FROM somewhere else TO the best-ranked hospital, which is the shape of
        # the scripted scenario: a district facility sending a case up the valley.
        source = psql(
            f"select id from hospitals where id <> '{destination['hospital_id']}' limit 1"
        )
        patient_id = psql("select id from patients order by created_at limit 1")
        placed = a.http.post(
            "/api/v1/referrals",
            json={
                "from_hospital_id": source,
                "to_hospital_id": destination["hospital_id"],
                "patient_id": patient_id,
                "specialty": "General Surgery",
                "urgency": "EMERGENCY",
                "notes": "demo-check",
            },
        )
        referral = placed.json() if placed.status_code == 201 else {}
        report(
            "referral reserves a bed at the destination",
            referral.get("status") == "RESERVED" and bool(referral.get("bed")),
            f"{referral.get('status')} — bed {referral.get('bed')} at {destination['hospital']}",
        )
        # It has to be visible to the receiving hospital, not just to whoever placed it.
        inbox = a.http.get(f"/api/v1/referrals?to_hospital_id={destination['hospital_id']}").json()
        report(
            "destination sees the hold on its own list",
            any(r["id"] == referral.get("id") for r in inbox),
            f"{len(inbox)} referral(s) inbound",
        )

        # And give the bed straight back. A demo-check that leaves a bed RESERVED
        # forever is exactly the rot this script had before today.
        if referral.get("id"):
            a.http.post(f"/api/v1/referrals/{referral['id']}/cancel")
            freed = psql(
                "select state from beds where id = "
                f"(select reserved_bed_id from referrals where id = '{referral['id']}')"
            )
            print(f"  [restored] referral cancelled, bed released ({freed or 'FREE'})")
    else:
        report(
            "referral reserves a bed at the destination",
            False,
            "no viable destination to refer to",
        )

    a.close()
    fails = [s for s, ok, _ in results if not ok]
    print(f"\n{len(results)-len(fails)}/{len(results)} PASS")
    if fails:
        print("FAILED:", ", ".join(fails))
    sys.exit(1 if fails else 0)


asyncio.run(main())

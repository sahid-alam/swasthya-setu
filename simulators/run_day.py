"""Plays every persona for the seeded doctors at configurable time-compression.

    python simulators/run_day.py --seed 42 --speed 120 --minutes 4

`--speed 120` means one simulated hour takes 30 real seconds. The backend scales its
decay constants by the same SIM_SPEED, so a compressed day behaves like a real one.
"""

from __future__ import annotations

import argparse
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from client import Setu, Signal  # noqa: E402
from personas import DEFAULT_MIX, PERSONAS, script_for  # noqa: E402


def build_timeline(roster: dict, rng: random.Random, only_hospital: str | None) -> list[tuple[Signal, str]]:
    zones_by_hospital: dict[str, list[dict]] = {}
    for z in roster["zones"]:
        zones_by_hospital.setdefault(z["hospital_code"], []).append(z)

    timeline: list[tuple[Signal, str]] = []
    for i, doctor in enumerate(roster["doctors"]):
        if only_hospital and doctor["hospital_code"] != only_hospital:
            continue
        persona = DEFAULT_MIX[i % len(DEFAULT_MIX)]
        zones = zones_by_hospital.get(doctor["hospital_code"], [])
        for signal in script_for(doctor, zones, persona, rng):
            timeline.append((signal, persona))
    timeline.sort(key=lambda pair: pair[0].at)
    return timeline


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=42, help="same seed -> same day, every rehearsal")
    ap.add_argument("--speed", type=int, default=120, help="time compression (SIM_SPEED)")
    ap.add_argument("--minutes", type=float, default=5.0, help="real minutes to run for")
    ap.add_argument("--hospital", default=None, help="limit to one hospital code")
    ap.add_argument("--dry-run", action="store_true", help="print the plan, send nothing")
    args = ap.parse_args()

    rng = random.Random(args.seed)
    api = Setu()
    try:
        roster = api.roster()
        timeline = build_timeline(roster, rng, args.hospital)
        budget = args.minutes * 60 * args.speed  # how much simulated time we can cover
        timeline = [(s, p) for s, p in timeline if s.at <= budget]

        personas = sorted({p for _, p in timeline})
        print(
            f"{len(timeline)} signals over {budget / 3600:.1f} simulated hours "
            f"({args.minutes:.1f} real min at {args.speed}x) — personas: {', '.join(personas)}"
        )
        if args.dry_run:
            for signal, persona in timeline[:20]:
                print(f"  t+{signal.at:7.0f}s {persona:<13} {signal.source:<5} "
                      f"{signal.badge_id} -> {signal.zone_code}")
            return 0

        started = time.monotonic()
        sent = flips = 0
        for signal, _persona in timeline:
            due = started + signal.at / args.speed
            delay = due - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            result = api.send(signal)
            sent += 1
            flips += int(result["changed"])
            if result["changed"]:
                print(f"  t+{signal.at:7.0f}s {signal.badge_id} -> {result['state']} "
                      f"({result['confidence']:.2f})")
        print(f"done: {sent} signals sent, {flips} state changes")
        return 0
    finally:
        api.close()


if __name__ == "__main__":
    raise SystemExit(main())

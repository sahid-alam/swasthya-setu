"""Named triggers the command-centre admin panel calls — the presenter's remote
control. Every scenario in the demo script lives here and has a matching test.

    python simulators/scenario.py doctor_absent HP-DOC-1001
    python simulators/scenario.py beacon_dead  HP-DOC-1002
    python simulators/scenario.py walk_to_surgery HP-DOC-1003
"""

from __future__ import annotations

import argparse
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from client import Setu, Signal  # noqa: E402


def _find(roster: dict, badge: str) -> dict:
    for doctor in roster["doctors"]:
        if doctor["badge_id"] == badge:
            return doctor
    raise SystemExit(f"no doctor with badge {badge}")


def _zones(roster: dict, hospital_code: str) -> list[dict]:
    return [z for z in roster["zones"] if z["hospital_code"] == hospital_code]


def _zone_code(zones: list[dict], kind: str, department: str | None = None) -> str:
    for z in zones:
        if z["kind"] == kind and (department is None or z["department"] == department):
            return z["code"]
    return next(z["code"] for z in zones if z["kind"] == kind)


def doctor_absent(api: Setu, roster: dict, badge: str) -> None:
    """The 9 AM phone call. An admin override, so the board explains itself as
    "set by hand, with a reason" rather than as a mystery."""
    doctor = _find(roster, badge)
    result = api.override(doctor["doctor_id"], "ON_LEAVE", f"Called in sick — {doctor['name']}")
    print(f"{doctor['name']} -> {result['state']} (changed={result['changed']})")


def beacon_dead(api: Setu, roster: dict, badge: str) -> None:
    """Stops BLE only. Nothing more is sent, so the next sweep must decay this
    doctor off PRESENT instead of leaving a stale green chip on the board."""
    doctor = _find(roster, badge)
    zones = _zones(roster, doctor["hospital_code"])
    api.send(Signal(at=0, source="BLE", badge_id=badge,
                    zone_code=_zone_code(zones, "OPD", doctor["department"]),
                    raw={"rssi": -61, "battery": "low"}))
    print(f"{doctor['name']}: last BLE ping sent, beacon now silent — watch it decay")


def walk_to_surgery(api: Setu, roster: dict, badge: str) -> None:
    """The "show me a doctor walking from OPD to surgery" demo."""
    doctor = _find(roster, badge)
    zones = _zones(roster, doctor["hospital_code"])
    opd = _zone_code(zones, "OPD", doctor["department"])
    ot = _zone_code(zones, "OT")

    for _ in range(2):
        print("  OPD ->", api.send(Signal(at=0, source="BLE", badge_id=badge, zone_code=opd,
                                          raw={"rssi": -64}))["state"])
        time.sleep(0.4)
    print("  theatre door ->",
          api.send(Signal(at=0, source="RFID", badge_id=badge, zone_code=ot,
                          raw={"reader": "ot-door"}))["state"])


def arrives(api: Setu, roster: dict, badge: str) -> None:
    """A doctor turning up: gate tap then badge pings in their own OPD."""
    doctor = _find(roster, badge)
    zones = _zones(roster, doctor["hospital_code"])
    rng = random.Random(badge)
    api.send(Signal(at=0, source="RFID", badge_id=badge, zone_code=_zone_code(zones, "GATE")))
    for _ in range(2):
        time.sleep(0.4)
        out = api.send(Signal(at=0, source="BLE", badge_id=badge,
                              zone_code=_zone_code(zones, "OPD", doctor["department"]),
                              raw={"rssi": rng.randint(-80, -55)}))
    print(f"{doctor['name']} -> {out['state']} ({out['confidence']:.2f})")


SCENARIOS = {
    "doctor_absent": doctor_absent,
    "beacon_dead": beacon_dead,
    "walk_to_surgery": walk_to_surgery,
    "arrives": arrives,
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("scenario", choices=sorted(SCENARIOS))
    ap.add_argument("badge", help="badge id, e.g. HP-DOC-1001")
    args = ap.parse_args()

    api = Setu()
    try:
        SCENARIOS[args.scenario](api, api.roster(), args.badge)
        return 0
    finally:
        api.close()


if __name__ == "__main__":
    raise SystemExit(main())

"""Movement scripts. A persona turns one doctor + their hospital's zones into a
timed list of sightings, in simulated seconds from the start of the run.

Realism is the point: jittered intervals, noisy RSSI and occasional dropped pings are
what make the fused state look like a real building instead of a metronome. A judge
who sees perfectly regular 60s pings correctly stops believing the demo.
"""

from __future__ import annotations

import random

from client import Signal

HOUR = 3600


def _zone(zones: list[dict], kind: str, department: str | None = None) -> str | None:
    for z in zones:
        if z["kind"] == kind and (department is None or z["department"] == department):
            return z["code"]
    return next((z["code"] for z in zones if z["kind"] == kind), None)


def _ble_train(
    badge: str, zone: str, start: float, end: float, rng: random.Random, drop_rate: float = 0.08
) -> list[Signal]:
    """A badge seen repeatedly in one zone: every 30-90s, with dropouts."""
    out, t = [], start
    while t < end:
        if rng.random() > drop_rate:  # a real beacon misses scans
            out.append(
                Signal(
                    at=t,
                    source="BLE",
                    badge_id=badge,
                    zone_code=zone,
                    raw={"rssi": rng.randint(-82, -55)},
                )
            )
        t += rng.uniform(30, 90)
    return out


def opd_day(doctor: dict, zones: list[dict], rng: random.Random) -> list[Signal]:
    """Arrives at the gate, works OPD, disappears for a tea break, comes back."""
    badge = doctor["badge_id"]
    gate = _zone(zones, "GATE")
    opd = _zone(zones, "OPD", doctor["department"])
    lobby = _zone(zones, "LOBBY")

    out = [Signal(at=0, source="RFID", badge_id=badge, zone_code=gate, raw={"reader": "gate-in"})]
    out.append(Signal(at=60, source="WIFI", badge_id=badge, zone_code=lobby, raw={"ap": "lobby-1"}))
    out += _ble_train(badge, opd, 3 * 60, 2 * HOUR, rng)
    # tea break: no signal at all for ~25 minutes. Presence must decay, not pretend.
    out += _ble_train(badge, opd, 2 * HOUR + 25 * 60, 4 * HOUR, rng)
    return out


def surgery_day(doctor: dict, zones: list[dict], rng: random.Random) -> list[Signal]:
    """The "walking from OPD to surgery" demo: OPD, then a gate tap into theatre."""
    badge = doctor["badge_id"]
    opd = _zone(zones, "OPD", doctor["department"])
    ot = _zone(zones, "OT")

    out = [Signal(at=0, source="RFID", badge_id=badge, zone_code=_zone(zones, "GATE"))]
    out += _ble_train(badge, opd, 2 * 60, 90 * 60, rng)
    # RFID at the theatre door is high-trust, so the board flips immediately
    out.append(Signal(at=92 * 60, source="RFID", badge_id=badge, zone_code=ot, raw={"reader": "ot-door"}))
    out += _ble_train(badge, ot, 95 * 60, 4 * HOUR, rng)
    return out


def ward_rounds(doctor: dict, zones: list[dict], rng: random.Random) -> list[Signal]:
    badge = doctor["badge_id"]
    out = [Signal(at=0, source="RFID", badge_id=badge, zone_code=_zone(zones, "GATE"))]
    out += _ble_train(badge, _zone(zones, "WARD"), 5 * 60, 2 * HOUR, rng)
    out += _ble_train(badge, _zone(zones, "OPD", doctor["department"]), 2 * HOUR, 4 * HOUR, rng)
    return out


def late_arrival(doctor: dict, zones: list[dict], rng: random.Random) -> list[Signal]:
    """Rostered from the start of the day but not actually here for 90 minutes.
    Until the gate tap the board should read the roster guess at low confidence."""
    badge = doctor["badge_id"]
    start = 90 * 60
    out = [Signal(at=start, source="RFID", badge_id=badge, zone_code=_zone(zones, "GATE"))]
    out += _ble_train(badge, _zone(zones, "OPD", doctor["department"]), start + 3 * 60, 4 * HOUR, rng)
    return out


def absent_day(doctor: dict, zones: list[dict], rng: random.Random) -> list[Signal]:
    """Rostered, never arrives. Emits nothing — the absence is the signal, and the
    roster-vs-presence mismatch is what the command centre should alert on."""
    return []


def beacon_dies(doctor: dict, zones: list[dict], rng: random.Random) -> list[Signal]:
    """Present, then the badge battery goes flat. Confidence must decay to a
    roster-based state rather than sitting on a stale PRESENT (PRD §M1)."""
    badge = doctor["badge_id"]
    opd = _zone(zones, "OPD", doctor["department"])
    out = [Signal(at=0, source="RFID", badge_id=badge, zone_code=_zone(zones, "GATE"))]
    out += _ble_train(badge, opd, 2 * 60, 40 * 60, rng)
    return out  # ...and then silence, for the rest of the day


PERSONAS = {
    "opd_day": opd_day,
    "surgery_day": surgery_day,
    "ward_rounds": ward_rounds,
    "late_arrival": late_arrival,
    "absent_day": absent_day,
    "beacon_dies": beacon_dies,
}

# What a normal seeded day looks like: mostly ordinary, with the interesting cases
# sprinkled in so the dashboard has something to show without a scenario trigger.
DEFAULT_MIX = (
    ["opd_day"] * 6 + ["surgery_day"] * 2 + ["ward_rounds"] * 2 + ["late_arrival", "beacon_dies"]
)


def script_for(doctor: dict, zones: list[dict], persona: str, rng: random.Random) -> list[Signal]:
    signals = PERSONAS[persona](doctor, zones, rng)
    return sorted([s for s in signals if s.zone_code], key=lambda s: s.at)

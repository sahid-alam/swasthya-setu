---
name: signal-simulator
description: Pattern for simulating hardware presence signals (BLE beacons, RFID gates, Wi-Fi geofence, face kiosk) and demo scenarios. Use when building anything in simulators/, the signal ingestion API, or dashboard scenario triggers.
---

# Signal Simulator Pattern

The presence engine must be indistinguishable whether signals come from real hardware or `simulators/`. Judges will see simulators driving the demo — that is by design and stated honestly.

## Core rule

Simulators are external clients: they POST to the same public `POST /api/v1/signals` endpoint real hardware would, with identical payloads:

```json
{"source": "BLE", "badge_id": "HP-DOC-0042", "zone_code": "SHIMLA-OPD-2",
 "observed_at": "...", "raw": {"rssi": -67}}
```

Never inject signals by writing to the DB directly or calling services in-process — that would make the demo a lie.

## Simulator components (`simulators/`)

- `personas.py` — movement scripts per doctor: e.g. `opd_day` (gate RFID → OPD BLE every 30–90s → canteen gap → OPD), `surgery_day`, `absent_day`, `late_arrival`. Timings jittered; RSSI noisy; occasional dropped pings (realism = credibility).
- `run_day.py` — plays all personas for seeded doctors at configurable time-compression (e.g. 1 sim-hour = 30 real seconds for the demo).
- `scenario.py` — named triggers the dashboard admin panel calls: `doctor_absent(doctor_id)`, `doctor_leaves_early`, `surge(department_id)`, `beacon_dead(doctor_id)` (stops BLE only — tests decay), `emergency(lat, lng)`.
- `face_mock.py` — for kiosk check-in, POSTs a precomputed embedding for an enrolled seed doctor (InsightFace runs server-side either way).

## Requirements

- Deterministic with a seed (`--seed 42`) so demo rehearsals are reproducible.
- Every scenario used in the demo script must also exist as an integration test asserting the expected state transitions.
- Time-compression must be configurable via env (`SIM_SPEED`), and the fusion decay constants must scale with it.
- The dashboard scenario panel (admin-only) is the presenter's remote control — every `scenario.py` trigger gets a button there.

# Architecture

## System shape

Monolith-first: one FastAPI app with clean internal service modules, one React PWA, workers as asyncio tasks inside the app (Celery only if genuinely needed — it hasn't been yet). Microservices are a Tier 3 slide, not a build target.

```
[Simulators / Hardware / Vendors]
        │  signals & webhooks
        ▼
┌─────────────────────────────── FastAPI (backend/) ───────────────────────────────┐
│ adapters/        channel + integration adapters, each with MOCK_MODE             │
│ services/presence    fusion state machine  ──┐                                   │
│ services/scheduling  CP-SAT + ML inference ◄─┼── reads live availability         │
│ services/notify      event → channel fan-out │                                   │
│ services/beds, blood, forecast, router, referrals                                │
│ api/v1/          thin routers               events: Redis pub/sub                │
└───────────────┬───────────────────────────────────────┬─────────────────────────┘
                │ SQLAlchemy                            │ /ws/dashboard, /ws/patient
           PostgreSQL 16                          React PWA (frontend/)
           Redis 7 (cache, pub/sub, queues)       CouchDB ⇄ PouchDB (offline)
```

## Data flow: the spine

1. Signal arrives: `POST /api/v1/signals` (from `simulators/` or real hardware — identical payload).
2. `services/presence` updates the doctor's fused state; writes `presence_events`, updates `doctor_status`; publishes `presence.changed`.
3. `services/scheduling` subscribes; if the change invalidates bookings, runs CP-SAT replan over the affected horizon; writes new assignments; publishes `appointments.replanned`.
4. `services/notify` fans out to channel adapters (WhatsApp/SMS/TTS/PWA push); logs every delivery in `notifications`.
5. Dashboard receives `presence.changed` + `queue.updated` over WebSocket. Nothing polls.

## Presence fusion design

- Per-signal trust weights (config, not code): RFID 0.9, face 0.95, BLE 0.7, Wi-Fi 0.5, roster 0.3, manual override 1.0.
- Each observation contributes weight × exp(-Δt/τ) toward candidate states; τ per signal type (BLE ~5 min, roster = shift length).
- State = argmax over candidates if score ≥ threshold, else degrade toward roster-implied state, else `UNKNOWN`. Hysteresis: require 2 consecutive wins or one high-trust signal to flip, preventing flicker.
- Every transition row stores: prior state, new state, contributing observations (ids), score. This evidence trail IS the judge answer.

## Adapter pattern (all external services)

`adapters/base.py` defines per-domain interfaces (`MessagingAdapter`, `TelephonyAdapter`, `HealthRegistryAdapter`, `BloodBankAdapter`, `RoutingAdapter`). Each vendor gets `<vendor>_real.py` + `<vendor>_mock.py`; a factory reads `<VENDOR>_MOCK_MODE` env var. Mocks are first-class: they persist to the same tables (e.g., mock WhatsApp writes to `notifications` with `channel=whatsapp, mock=true`) and appear in a dev "outbox" UI so the demo can show messages without vendor accounts. Business logic imports only the interface. See `.claude/skills/integration-adapter/SKILL.md` before adding any integration.

## Scheduling design

- CP-SAT model: variables = (appointment → slot) assignments; hard constraints: doctor available (from live availability windows), room capacity, no overlap, priority-class ordering; soft objectives (weighted): minimize weighted wait, minimize reschedule displacement, honor patient time preferences, cap overbooking by no-show probability.
- Replan scope: only the affected doctor(s) × remaining day, warm-started from current plan — this is why <5s is achievable.
- ML inference: load artifacts from `ml/artifacts/` at startup; versions pinned in `ml/artifacts/MANIFEST.json`; `/api/v1/metrics/models` exposes eval metrics for the honesty slide.

## Events (Redis pub/sub topics)

| Topic | Payload core | Consumers |
|---|---|---|
| `presence.changed` | doctor_id, old, new, confidence | scheduling, dashboard |
| `appointments.replanned` | appointment_ids, plan_version | notify, dashboard |
| `queue.updated` | department_id, queue snapshot | dashboard, patient ws |
| `bed.state_changed` | bed_id, state | dashboard, referrals |
| `referral.updated` | referral_id, status | both hospitals' dashboards |
| `alert.raised` | type, severity, context | dashboard |

WebSocket endpoints simply relay subscribed topics: `/ws/dashboard?hospital_id=` (staff JWT), `/ws/patient` (own appointments only). Token rides the query string — browsers cannot set headers on a WebSocket.

The first frame on any socket is `ws.ready`, sent once Redis has acknowledged the subscription. An open socket is not yet a subscribed one, so without it neither a client nor a test can tell a missed event from a slow one.

## Offline strategy (PWA)

Bookings made offline go to a local PouchDB `outbox`; on reconnect they sync to CouchDB, a backend worker validates against live slots and either confirms or proposes the nearest alternative (never silently books a taken slot). Read models (my appointments, hospital info) are cached for offline display with a "last synced" stamp.

## Key decisions log

| # | Decision | Why | Revisit if |
|---|---|---|---|
| D1 | Monolith + internal services | Team of students, 3 months, one demo | Never (pre-finals) |
| D2 | Simulator-first for all signals | Hardware can't be assumed at venue | Hardware confirmed → run both |
| D3 | Warm-started partial replans | Full-day global solve too slow for live demo | Solve times regress |
| D4 | Mock adapters persist real rows | Demo must show messages w/o vendor accounts | — |
| D5 | Models trained offline, artifacts committed | Training must never block or flake | Artifact >100MB → use release assets |
| D6 | CouchDB only for PWA outbox/read-cache | Full offline DB sync is a rabbit hole | — |
| D7 | Compose is canonical; `make dev-local` runs the same stack off host postgres/redis | Not every dev machine has Docker; blocking on it stalls the build | — |
| D8 | Fonts self-hosted as woff2, never fetched at runtime | DESIGN.md §9b + Iron Rule 4: the PWA and the demo must render with no internet | — |
| D9 | `tokens.css` is both the token block and the Tailwind theme (v4 `@theme`) | One file to keep in sync with DESIGN.md §1 instead of two | Tailwind drops `@theme` |
| D10 | Settings only declares env vars that code reads | An unread `*_MOCK_MODE` flag reads as wired-up and silently isn't | — |
| D11 | FK delete rule follows nullability; `appointments.slot_id` is RESTRICT | Uniform CASCADE would let a deleted appointment erase its own outbox row — the evidence a judge asks to see | — |
| D12 | Fusion scores max-per-location, not sum | A person is in one place, so sightings compete. Summing made an hour of OPD pings unbeatable by one theatre-door tap — movement became undetectable | — |
| D13 | Trust gates belief; recency picks the current sighting | Ranking on trust alone pinned a doctor to the gate they had just walked through | — |
| D14 | A roster-derived state renders grey and labelled, never confident green | PRD §M1 "never silently stays PRESENT"; also the clearest way to show roster-vs-reality | — |
| D15 | Roster decides when slots exist; only a *confident* presence state removes them | Forward booking must keep working, but a low-confidence state IS the roster — letting it cancel clinics would be the system arguing with itself | — |
| D16 | Replan runs inline in the request that changed presence, not off the pub/sub topic | One moving part, atomic with the presence write, and it keeps the "<5s" claim measurable from a single request (worst case measured 226 ms) | Solve times approach the budget |
| D17 | Rebook rather than rewrite: original row kept as RESCHEDULED, new row links via `rescheduled_from` | Preserves the chain a patient (and a judge) can follow, and `appointments.slot_id` is RESTRICT so slots are only ever re-pointed | — |
| D18 | Wait-time model trains on simulated clinic days, labelled SYNTHETIC everywhere it surfaces | No public dataset gives per-position OPD waits; Iron Rule 5 says say so rather than imply otherwise | Real HMIS queue data arrives |
| D19 | Overbooking is capped at 3 per doctor per day, only on seats whose occupant is ≥50% likely to miss | Overbooking is a bet, and losing it means a real person waits in a corridor | Measured no-show calibration improves |

## Ports (dev)

backend 8000 · frontend 5173 · postgres 5432 · redis 6379 · couchdb 5984 · osrm 5000

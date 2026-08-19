# Build Plan

Work strictly top-to-bottom within a phase. Do not start a phase until the previous phase's exit criteria pass. Tick `[x]` only when tested. Append to the Session Log every session.

## Phase 0 — Foundation (target: ~1 week part-time)

- [x] Monorepo scaffold per CLAUDE.md layout; Makefile with all targets (stub ok)
- [ ] `infra/docker-compose.yml`: postgres, redis, couchdb, backend (hot reload), frontend (Vite dev) — *written, never run: no Docker on this machine*
- [x] FastAPI skeleton: settings via pydantic-settings, `/api/v1/health`, error handling, CORS
- [x] Alembic initialized; migration 0001 = full schema from `docs/SCHEMA.md`
- [x] Auth: JWT, roles (admin, doctor, staff, patient); seed admin user
- [x] React PWA scaffold: Vite + Tailwind, service worker, login, empty dashboard shell
- [x] Design system as code: Tailwind theme + `tokens.css` from `docs/DESIGN.md` §1 (colors, radii, shadows, fonts self-hosted); base components per §6+§8: Panel, Button (5 variants), Chip (status pairings from §9d), FieldBlock, Eyebrow, TableShell; fade-up/modal-in motion utilities. Storybook-style `/dev/ui` route rendering all of them for visual verification
- [x] WebSocket channel `/ws/dashboard` + Redis pub/sub bridge; test event round-trips to browser
- [x] Seed script: 3 hospitals, departments, 30 doctors, rosters, 200 patients
- [x] CI-lite: `make test` and `make lint` green on clean checkout — verified by dropping the
  database and role, then running `make bootstrap-local migrate seed test lint` from nothing

**Exit:** `make dev` brings up the full stack; login works; a published Redis event appears in the browser.
**Exit status:** 2 of 3 verified — login works and a `redis-cli publish` reached the browser with no refresh. `make dev` is unverified because Docker is not installed here; `make dev-local` covers the same stack from host postgres/redis and is what was actually exercised.

## Phase 1 — Tier 1 vertical slice (target: ~4 weeks part-time)

Order matters: presence → optimizer → one channel → dashboard, then widen.

### 1A. Presence engine
- [ ] Signal ingestion API `POST /api/v1/signals` (schema in ARCHITECTURE.md)
- [ ] Simulators: BLE, RFID, Wi-Fi geofence, roster feed (see `.claude/skills/signal-simulator/`)
- [ ] Fusion state machine + confidence scoring; transitions persisted with evidence
- [ ] Face kiosk check-in endpoint (InsightFace, enrolled doctors only; simulator provides embeddings)
- [ ] Manual admin override with audit log
- [ ] Unit tests: decay, conflicting signals, roster fallback

### 1B. Appointment & queue engine
- [ ] Slot model + availability derivation from presence + roster
- [ ] CP-SAT allocation service with priority classes; benchmark <5s for 1-hospital day
- [ ] No-show model: train offline on 110k dataset, commit artifact, inference endpoint, metrics endpoint
- [ ] Wait-time model: features + committed artifact + per-queue-position prediction
- [ ] Auto-reschedule pipeline: presence change → replan → notification fan-out (events only for now)
- [ ] SimPy comparison script: CP-SAT vs FCFS on identical demand (produces the judge chart)

### 1C. Patient access core
- [ ] Booking API (channel-agnostic): search slots, book, cancel, reschedule
- [ ] PWA booking flow (Hindi + English), queue position view, offline PouchDB queue + sync
- [ ] WhatsApp adapter (mock mode default) with guided flow
- [ ] SMS adapter (mock mode default): confirmations + reschedule notices
- [ ] Notification service consuming reschedule events → channel fan-out with delivery log

### 1D. Command center
- [ ] Presence board (live, per hospital/department)
- [ ] Queue view with predicted waits
- [ ] Alerts: roster-vs-presence mismatch, queue overflow
- [ ] Network map (Leaflet) with facility status
- [ ] Scenario triggers panel (admin-only): "doctor absent", "surge" — drives simulators

**Exit (the spine demo):** doctor marked absent via simulator → dashboard flips → 40 appointments re-optimized <5s → mock WhatsApp/SMS log shows notifications → patient PWA shows new slot. Runs clean 3× in a row.

## Phase 2 — Tier 2 (target: ~4 weeks part-time)

- [ ] IVR adapter (Exotel, mock telephony) end-to-end booking
- [ ] Bhashini voice booking (constrained intent flow, mock mode + sandbox)
- [ ] Outbound TTS reschedule calls (mock mode)
- [ ] Kiosk mode skin for PWA
- [ ] Bed management: inventory, states, occupancy dashboard
- [ ] Referral reservation flow with expiry (M5 accept scenario)
- [ ] e-RaktKosh ingest job + blood widget (real snapshot + labeled fallback)
- [ ] Prophet footfall model on HMIS data + backtest chart endpoint
- [ ] Golden Hour Router: OSRM container with HP extract, ranking service, map UI
- [ ] Integration backbone: adapter interfaces + mocks for ABDM/eSanjeevani/108/e-Hospital; one live ABDM sandbox call

**Exit:** each Tier 2 module passes its PRD accept scenario independently.

## Phase 3 — Hardening & demo polish (target: ~2 weeks)

- [ ] `make demo`: full seeded day + scripted scenario, offline, clean machine
- [ ] `infra/demo-script.md`: presenter click-path, timings, fallback plan
- [ ] Judge Q&A doc assembled from `/defend` outputs
- [ ] Load sanity: 1 hospital-day replan under 5s with 3 hospitals seeded
- [ ] Failure drills: kill redis / kill a simulator mid-demo → graceful degradation visible
- [ ] UI polish pass on Tier 1 screens against `docs/DESIGN.md`: command-center flair (dark dock sidebar, veil transition, grain, kinetic headlines) per §9a; verify PWA/kiosk have NO heavy effects per §9b/§9c; audit every screen for raw hexes vs tokens and 3m projector legibility of live-state text

---

## Session Log

Append one entry per session: date · phase/items touched · decisions made · anything a fresh session must know.

<!-- e.g.
### 2026-09-02
- Phase 0: compose + FastAPI skeleton done. Decided couchdb waits until 1C (not blocking).
- Gotcha: alembic autogenerate misses the enum types; write them manually.
-->

### 2026-08-19

**Done:** Phase 0, 9 of 10 items. Backend (FastAPI + SQLAlchemy 2 + Alembic + JWT + Redis
pub/sub → `/ws/dashboard`), full schema migration, deterministic seed, React 18 PWA with the
MediCore design system and a `/dev/ui` sheet. 12 backend + 5 frontend tests, `make lint` and
`make test` green.

**Verified end-to-end in a real browser:** logged in as the seeded admin, then
`redis-cli publish presence.changed …` appeared on the dashboard with no interaction.

**Environment (this machine has no Docker):** postgres 17 + redis 8 run from Homebrew.
`make dev-local` is the path that works here; `make dev` (compose) is written but unrun.
From a clean checkout: `make install bootstrap-local migrate seed test`. If
`brew services start redis` refuses to start, comment out the four `loadmodule` lines in
`/opt/homebrew/etc/redis.conf` — the bottle does not ship those modules.

**Decisions:**
- FK delete rules are derived, not uniform: nullable → `SET NULL`, required → `CASCADE`,
  and `appointments.slot_id` → `RESTRICT`. Written into SCHEMA.md and pinned by
  `tests/test_schema.py`. Caught while 0001 was still unshipped, so it was a regenerate
  rather than a data migration.
- Chip colour pairings live in `tokens.css` as `--chip-*-bg/fg`; components carry zero
  hexes. `--live-state-size: 15px` resolves the §6-vs-§9a conflict (11px chip text vs the
  3m projector rule) in favour of §9a for anything showing live state.
- Fonts are self-hosted woff2 in `frontend/src/fonts/`. DESIGN.md §1 offers a Google Fonts
  `@import`; §9b and Iron Rule 4 forbid a runtime fetch, so §9b wins. Do not paste that
  `@import` into `tokens.css`.
- Tailwind v4 `@theme` makes `tokens.css` both the token block and the Tailwind theme — one
  file, no `tailwind.config.js`. DESIGN.md's unprefixed names (`--primary`) are aliased to the
  tailwind-namespaced ones so CSS can be copied out of the doc verbatim.
- `users` gained a `name` column, folded into migration 0001 (not yet shipped, so no 0002).
  `docs/SCHEMA.md` updated in the same commit. Without it every doctor renders as a UUID.
- `app/config.py` declares a setting only when code reads it. `COUCHDB_URL`, `SIM_SPEED` and
  the `*_MOCK_MODE` flags stay in `.env.example` but are not in `Settings` yet — a flag that
  appears in that class is one that actually does something.
- Python pinned to 3.11 via `uv` (host is 3.12) to match CLAUDE.md and the compose image.

**Gotchas for the next session:**
- Alembic autogenerate really does double-create PG enums — any type used by two tables
  (`presence_state`, `channel`) emits `CREATE TYPE` twice. 0001 creates all 23 up front and
  every column references them with `create_type=False`. Keep that shape in 0002.
- `TestClient` deadlocks if you make an HTTP call inside a `websocket_connect` block.
  `tests/test_events.py` publishes with the sync redis client instead.
- Subscribing to Redis is async, so an accepted socket is not yet a listening one. Every
  socket now gets a `ws.ready` first frame; tests wait for it before publishing. Counting
  subscribers instead is wrong — a running dev server is also a subscriber, which is what
  made the suite hang until this was fixed. Any new WS test must wait for `ws.ready`.
- Restart uvicorn after a migration: asyncpg caches prepared statements and throws
  `InvalidCachedStatementError` on the first request against a changed schema.
- Port 5173 was occupied by another project, so Vite fell back to 5174. The proxy handles
  `/api` and `/ws`, so CORS never came into play.

**Next session picks up:** Phase 1A, first item — `POST /api/v1/signals` ingestion.
Read PRD §M1 and `.claude/skills/signal-simulator/` first. Also still open from Phase 0:
run `make dev` once Docker exists on some machine, and decide the Supabase question raised
in chat (see below).

**Open question raised in chat, not decided:** using Supabase. It conflicts with Iron Rule 4
(hosted Postgres means no offline demo) and with the fixed stack, but Supabase-as-managed-
Postgres for a shared team dev DB would work unchanged — SQLAlchemy/Alembic only need the
connection string. Needs a team decision, no code was written either way.

# Build Plan

Work strictly top-to-bottom within a phase. Do not start a phase until the previous phase's exit criteria pass. Tick `[x]` only when tested. Append to the Session Log every session.

## Phase 0 — Foundation (target: ~1 week part-time)

- [ ] Monorepo scaffold per CLAUDE.md layout; Makefile with all targets (stub ok)
- [ ] `infra/docker-compose.yml`: postgres, redis, couchdb, backend (hot reload), frontend (Vite dev)
- [ ] FastAPI skeleton: settings via pydantic-settings, `/api/v1/health`, error handling, CORS
- [ ] Alembic initialized; migration 0001 = full schema from `docs/SCHEMA.md`
- [ ] Auth: JWT, roles (admin, doctor, staff, patient); seed admin user
- [ ] React PWA scaffold: Vite + Tailwind, service worker, login, empty dashboard shell
- [ ] Design system as code: Tailwind theme + `tokens.css` from `docs/DESIGN.md` §1 (colors, radii, shadows, fonts self-hosted); base components per §6+§8: Panel, Button (5 variants), Chip (status pairings from §9d), FieldBlock, Eyebrow, TableShell; fade-up/modal-in motion utilities. Storybook-style `/dev/ui` route rendering all of them for visual verification
- [ ] WebSocket channel `/ws/dashboard` + Redis pub/sub bridge; test event round-trips to browser
- [ ] Seed script: 3 hospitals, departments, 30 doctors, rosters, 200 patients
- [ ] CI-lite: `make test` and `make lint` green on clean checkout

**Exit:** `make dev` brings up the full stack; login works; a published Redis event appears in the browser.

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

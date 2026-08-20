# Build Plan

Work strictly top-to-bottom within a phase. Do not start a phase until the previous phase's exit criteria pass. Tick `[x]` only when tested. Append to the Session Log every session.

## Phase 0 — Foundation (target: ~1 week part-time)

- [x] Monorepo scaffold per CLAUDE.md layout; Makefile with all targets (stub ok)
- [x] `infra/docker-compose.yml`: postgres, redis, backend (hot reload), frontend (Vite dev) — verified up on 2026-08-20 (five containers then; couchdb since removed, D23). **Re-verified 2026-08-21** with `libgomp1` + `../ml:/ml:ro`: migrations run to `0003`, `metrics/models` reports `loaded: true` (XGBoost finds libgomp), login works, and `make demo-check` is 8/8 against the containers (`OPTIMAL` 233 ms). Stop brew postgres/redis first — compose publishes 5432/6379 and will not bind otherwise. First build pulls ~500 MB (xgboost drags in `nvidia-nccl-cu12`) and takes ~10 min; afterwards the `.venv` volume makes it fast.
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
**Exit status:** all 3 verified. `make dev` brought the full stack up on 2026-08-20 once Docker was installed; login works; a `redis-cli publish` reaches the browser with no refresh. `make dev-local` remains the no-Docker path.

## Phase 1 — Tier 1 vertical slice (target: ~4 weeks part-time)

Order matters: presence → optimizer → one channel → dashboard, then widen.

### 1A. Presence engine
- [x] Signal ingestion API `POST /api/v1/signals` (schema in ARCHITECTURE.md)
- [x] Simulators: BLE, RFID, Wi-Fi geofence, roster feed (see `.claude/skills/signal-simulator/`)
- [x] Fusion state machine + confidence scoring; transitions persisted with evidence
- [x] Face kiosk check-in endpoint — embedding matching + enrolment gate done; the
  InsightFace *extraction* step is not wired (a dev capture endpoint stands in for the
  camera). No production claim until a real kiosk feeds it.
- [x] Manual admin override with audit log
- [x] Unit tests: decay, conflicting signals, roster fallback

### 1B. Appointment & queue engine
- [x] Slot model + availability derivation from presence + roster
- [x] CP-SAT allocation service with priority classes; benchmark <5s for 1-hospital day —
  worst case 176 ms, median 12 ms across all 10 IGMC doctors
- [x] No-show model: train offline on 110k dataset, commit artifact, inference endpoint, metrics endpoint
- [x] Wait-time model: features + committed artifact + per-queue-position prediction —
  *trained on synthetic clinic days, labelled SYNTHETIC everywhere it surfaces*
- [x] Auto-reschedule pipeline: presence change → replan → notification fan-out (events only for now) —
  `appointments.replanned` verified arriving on the dashboard socket
- [x] SimPy comparison script: CP-SAT vs FCFS on identical demand (produces the judge chart)

### 1C. Patient access core
- [x] Booking API (channel-agnostic): search slots, book, cancel, reschedule
- [x] PWA booking flow (Hindi + English), queue position view, offline queue + sync —
  offline path verified in a browser (book offline → queue → reconnect → drains to 0).
  **Not PouchDB**: localStorage + REST replay, ARCHITECTURE D23 supersedes D6.
  Patient phone-OTP login now exists (`/patient`) — reuses the mock SMS adapter and the
  existing JWT, no new auth service. Staff/kiosk operation still works unchanged.
  **Queue position is API-only.** `/api/v1/me/queue` and `/api/v1/pwa/my-queue/{id}`
  serve position + predicted wait and `demo-check` asserts on them, but no PWA screen
  renders it (the `myQueue` / `positionLabel` strings sit unused in `lib/i18n.ts`).
  The patient's visible proof of a reschedule is the notification, not a screen.
- [x] WhatsApp adapter (mock mode default) with guided flow
- [x] SMS adapter (mock mode default): confirmations + reschedule notices
- [x] Notification service consuming reschedule events → channel fan-out with delivery log

### 1D. Command center
- [x] Presence board (live, per hospital/department) — brought forward from 1D for the
  20 Aug presentation; includes the evidence drawer ("how do you know?")
- [x] Queue view with predicted waits
- [x] Alerts: roster-vs-presence mismatch, queue overflow (+ patients pending rebooking)
- [x] Network map (Leaflet) with facility status — *basemap tiles need internet; their
  absence is detected and labelled, markers and every number still render (Iron Rule 4)*
- [x] Scenario triggers panel (admin-only) — drives the same public `/signals` endpoint
  the CLI simulators use, from the browser. "surge" not built; the five shipped are
  arrives / walk to surgery / beacon dies / calls in sick / roster is wrong

**Exit (the spine demo):** doctor marked absent via simulator → dashboard flips → 40 appointments re-optimized <5s → mock WhatsApp/SMS log shows notifications → patient PWA shows new slot. Runs clean 3× in a row.
**MET 2026-08-20** on `dev-local`, via `make seed && make demo-check` three times
consecutively: 8/8 each run, `OPTIMAL` in 156 / 196 / 164 ms, 39 patients moved (the
seed books 39, not 40), 39–41 WhatsApp/SMS outbox rows per run. The last hop is checked
through the PWA's own queue endpoint, not a rendered screen — see 1C below.

## Phase 2 — Tier 2 (target: ~4 weeks part-time)

- [x] IVR adapter (Exotel, mock telephony) end-to-end booking — `POST /channels/ivr/webhook`
  takes the provider's `CallSid`/`From`/`Digits` shape, `adapters/ivr_mock.py` translates it,
  and the keypad flow books through the same `services/booking.py` as every other channel.
  Three options per menu, not five: a caller has no screen to scroll. Verified end-to-end
  with `simulators/ivr_call.py` in both languages — confirmed appointments with
  `channel=IVR` and a `booked` receipt in the outbox. No `ivr_real.py`: no credentials yet.
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
- `app/config.py` declares a setting only when code reads it. `SIM_SPEED` and
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

### 2026-08-20

**Done:** Phase 1A complete (presence engine), plus the 1D presence board pulled forward
for a presentation. 43 backend + 5 frontend tests green, lint clean.

**Demo:** `infra/demo-script.md` is the presenter runbook — start commands, a seven-step
click path mapped to the PRD §M1 accept criteria, timings, and a failure table. Every step
in it was executed, not just written.

**Run it with** `PRESENCE_SWEEP_SECONDS=5 SIM_SPEED=12` — decay is then visible in ~25s
instead of ~5 minutes. The fusion maths is unchanged; only the tau constants scale.

**Docker now works** (user installed it). All five containers came up, migrations + seed
ran inside the container, and the M1 scenarios passed against the compose stack. One real
bug it exposed: the `../backend:/app` bind mount let the container's `uv sync` overwrite
the host `.venv` with `/app`-relative shebangs. Fixed with an anonymous volume on
`/app/.venv`, the same guard `node_modules` already had. If a host venv ever breaks this
way again: `uv venv --clear .venv && uv sync`.

**Tau is per signal *kind*, not per trust level:** RFID is 180s, shorter than BLE's 300s,
because a gate tap is a boundary crossing (informative for a minute) while BLE is a
repeated dwell signal. With RFID at 900s an old gate tap outlived the newer OPD pings and
dragged the doctor back to the door a minute after arriving — visible on the board as a
wobble. Pinned by `test_an_older_longer_lived_signal_does_not_resurrect_a_stale_location`.

**Four fusion bugs found by running the thing, not reading it** — all now pinned by tests:
- Summing observations per state meant 90 minutes of OPD pings could never be outvoted by
  one RFID tap at the theatre door, so *movement was undetectable*. Locations are mutually
  exclusive evidence: score is now max-per-place plus a capped corroboration bonus.
- Trust outranked recency, so a gate tap pinned a doctor to the door they had just walked
  through. Trust now decides whether a sighting is *believed*; recency decides which
  believed sighting is *current*.
- `JSONB` stores Python `None` as JSON `null`, not SQL NULL, so unenrolled doctors looked
  enrolled to `IS NOT NULL`. Needs `JSONB(none_as_null=True)`. Worth remembering for every
  future nullable JSONB column.

**Design decision worth keeping:** a roster-derived state renders grey and labelled
`ROSTER ONLY`, never confident green. Opening the board on a wall of grey is the strongest
part of the demo — it makes "we optimise against the roster, not reality" visible in one
glance, and it satisfies PRD §M1 "never silently stays PRESENT".

**Schema:** migration 0002 adds `zones.code` (what a reader is provisioned with; `name` is
a display string) and `doctors.face_embedding`. SCHEMA.md updated.

**Known gaps, stated honestly:**
- Face check-in does embedding *matching*, not embedding *extraction* — InsightFace is not
  wired; a dev-only, admin-gated capture endpoint stands in for the camera.
- Every signal triggers a full re-fusion and commit (~35 signals/sec measured). Fine for 3
  hospitals; revisit before any load claim.
- The scenario-trigger panel (1D) is not built — scenarios run from the CLI, which arguably
  demos better since it shows the simulator as a genuine external client.

**Next session picks up:** Phase 1B, first item — slot model + availability derivation from
presence + roster. Still open: the Supabase question (see 2026-08-19 entry).

### 2026-08-20 (later — Phase 1B)

**Done:** Phase 1B complete. 70 backend tests green, lint clean, suite stable over
three consecutive runs.

**The M2 flagship works end to end:** a doctor with 39 upcoming patients is marked on
leave; the clinic is redistributed automatically in ~300 ms (OPTIMAL, nobody dropped);
`presence.changed` and `appointments.replanned` both arrive on the dashboard socket.

**The availability rule (the M1/M2 hinge), settled in writing before any solver code:**
the roster decides when slots *exist*; a **confident** presence state removes them; a
low-confidence state changes nothing — because a low-confidence state *is* the roster,
and letting it cancel clinics would be the system arguing with itself. One function,
`services/availability.unavailability_for`, ARCHITECTURE D15.

**Benchmarks (real, not projected):** replanning every IGMC doctor in turn — worst case
176 ms, median 12 ms, 3.5% of the 5 s budget. The `plan_runs` table records every solve,
and `GET /scheduling/plan-runs` is the evidence, the same way `presence_transitions` is
the evidence for presence.

**Models.** No-show is trained on the real public 110,527-row dataset: ROC-AUC 0.735,
Brier 0.143 vs a 0.161 base-rate baseline. Wait-time has no real dataset to train on, so
it uses simulated clinic days and says SYNTHETIC in the manifest, the metrics file and
the API response. MAE 15.0 min vs the 27.3 min you get from `people ahead × consult
length`. `make train` regenerates all of it; the 10 MB source CSV is gitignored and its
sha256 is recorded in the artifact.

**The FCFS comparison did not say what we wanted, so it says what it found.** With spare
capacity CP-SAT does *not* reduce mean displacement — 23.1 vs 22.7 min, marginally
*worse* — it changes who waits, protecting referred (0 vs 25 min) and priority (8 vs 49
min) patients at general patients' expense. In a busy department, mean displacement is
71.8 vs 147.8 min (51% lower) and FCFS drops referred patients entirely. **Say "the right
people wait less", never "everyone waits less"** — the second claim is false and a judge
who probes will find that out.

**Two bugs worth remembering:**
- The first wait model scored a suspiciously good 1.3 min MAE because `minutes_into_clinic`
  was the time the patient was *actually seen* — the target was a function of the features.
  Refeatured to only what is knowable while standing in the queue. Any future model: ask
  what is knowable *at prediction time* before choosing features.
- Three `str.replace` patches to conftest silently no-op'd because the target text had
  drifted, and I chased a phantom test failure for several rounds. Use the Edit tool for
  surgical edits — it fails loudly on no-match — and reserve blind replace for fresh files.

**Docker:** compose now installs `libgomp1` (xgboost needs OpenMP on Debian, the same
problem `brew install libomp` fixes on macOS) and mounts `../ml:/ml:ro` so the committed
artifacts are reachable. Not re-run since those edits — verify before relying on it.

**Known gaps, stated honestly:**
- Replan runs inline in the request rather than off the pub/sub topic (D16). Fine at
  ~300 ms; revisit if solve times approach the budget.
- Unplaceable patients are CANCELLED. Correct-ish, but they need the 1C notification
  ("we could not find you a new slot") before this is defensible in front of a patient.
- Overbooking is implemented and capped but never fires in the seeded demo, because
  seeded no-show probabilities cluster near the 0.20 base rate and the threshold is 0.50.

**Next session picks up:** Phase 1C, first item — the channel-agnostic booking API.
Still open: the Supabase question (2026-08-19 entry).

### 2026-08-20 (later — 1B gaps closed, Phase 1C)

**demo-check discipline:** a baseline was taken *before* touching anything — 6/7, the
only FAIL being `notifications` (the 1C service that did not exist). Every item since
was followed by a re-run. Final state **7/7**. 99 backend + 12 frontend tests, lint clean,
suite stable over three consecutive runs.

**Supabase: closed, no.** Decision recorded; no code was ever written either way.

**1B gaps closed**
- Migration 0003 adds `RESCHEDULE_PENDING`. A replan that cannot seat someone no longer
  cancels them silently — `GET /scheduling/pending` lists them with name and phone so
  staff can actually ring them, and 1C now sends them a message saying so.
- The seed contains three genuinely high-risk bookings so overbooking is a feature
  someone has watched run: ~95 days lead time, no reminder, young patient — the profile
  the real 110k dataset flags. The model scores them 0.55 unaided. Verified: two seats
  offered to the solver at capacity 2.

**Phase 1C**
- `services/booking.py` is the single channel-agnostic implementation. PWA, WhatsApp and
  the kiosk all call it, so the same patient cannot get different answers by asking a
  different way.
- Adapters follow the skill exactly: interface first, mock first, factory on
  `*_MOCK_MODE` defaulting true. Mocks have realistic latency and a real failure rate,
  and write to `notifications` — that table is the demo outbox (D4).
- Message bodies live in `adapters/base.render`, Hindi and English, so channels cannot
  drift apart.
- PWA booking is Hindi-first and flair-free per §9b; offline booking queues locally and
  drains on reconnect, verified in a browser with the network actually cut.

**Four bugs found by looking at output rather than status codes:**
- The reschedule SMS named the *new* doctor as "unavailable" — it reads as a system
  error to the patient. `{doctor}` is now unambiguously who they will see.
- The WhatsApp flow read intent before state, so replying "1" to pick department 1
  restarted booking. State beats intent while a choice is pending.
- The menu fallback showed the menu without resetting state, so the next digit was read
  as a selection from a list the patient could no longer see.
- The SMS fallback test was flaky: the mock fails 3% of the time by design, so the test
  now seeds it. It is about the fallback firing, not gateway luck.

**Process note, third time now:** blind `str.replace` patches silently no-op when black
has reformatted the target since it was written. Use the Edit tool for surgical edits —
it fails loudly on no-match. Reserve `str.replace` for files written in the same step.

**Deferred by explicit decision:** Docker re-verification (compose gained `libgomp1` and
an `../ml:/ml:ro` mount but has not been re-run). The demo runs on `dev-local`.

**Known gaps, stated honestly:**
- Patient self-service auth does not exist. Nothing in the UI implies it does, but do not
  describe the PWA as "a patient logging in".
- WhatsApp conversation state is an in-process dict. Fine for one worker; needs Redis
  before a second one.
- IVR, Bhashini voice and the kiosk skin are Phase 2, untouched.

**Next session picks up:** Phase 1D — queue view with predicted waits, alerts
(roster-vs-presence mismatch), Leaflet network map, scenario triggers panel.

### 2026-08-20 (later — D23 docs, Redis sessions, Phase 1D, patient OTP)

**demo-check 7/7 after every item.** 113 backend + 12 frontend tests, lint clean.

**D23 approved and applied.** CLAUDE.md, SCHEMA.md, ARCHITECTURE (diagram, offline
strategy, ports) and PLAN now describe the localStorage outbox. The `couchdb` container
and `COUCHDB_URL` are gone from compose — CouchDB existed only to serve PouchDB, and a
dead service in `make dev` contradicts the rule we applied to unread config flags. Eight
lines to restore if a read-cache ever needs it.

**PRD.md still says "(PouchDB→CouchDB sync)" in §M3.** The hook blocks editing it, which
is correct — that is a scope document. Someone should change it by hand, or decide the
PRD wording stands and D23 is an implementation detail beneath it.

**WhatsApp state is in Redis** (`chat:whatsapp:{phone}`, 30 min TTL, D24). Structured as
load / run / save with exactly one persist point — the turn logic has eight return paths
and sprinkling a save before each is how you get the one that forgets. Proved it properly:
started a conversation, killed the backend mid-flow, started a new process, sent the next
digit, and it booked. An unrecognised number now gets an answer but no stored key.

**Phase 1D (dashboard).** Dock chrome per §4, queues with per-position predicted waits,
alerts computed on read, Leaflet network map, scenario trigger panel. The panel calls the
same public endpoints `simulators/scenario.py` calls, from the browser — nothing writes to
the database directly, because a scenario button that cheated would make the demo a lie.

**Iron Rule 4 catch on the map:** OSM basemap tiles need internet. Verified offline —
zero tiles load, all three markers still place correctly. The map now detects tile failure
and labels it rather than showing a blank rectangle; every number is in the table below.

**Patient phone-OTP login (D25)** on the existing mock SMS adapter and existing JWT. Eleven
tests cover the security properties, not just the happy path: `secrets` not `random`,
constant-time compare, single use, dead after 3 wrong guesses, rate limited, identical
response for an unknown number, code never in an HTTP response, SMS only, and a PATIENT
token 403s on every staff endpoint.

**Process, fourth and fifth occurrence:** blind `str.replace` bit twice more. Once a
multi-file patch script died on an assertion *after* writing file A but *before* writing
file B, leaving a half-applied change that typechecked and silently called the wrong
endpoint. Use Edit for surgical changes; if a script must patch several files, assert
every target up front, or verify each substitution landed afterwards.

**Known gaps:**
- Docker not re-verified since `libgomp1` + the `../ml:/ml:ro` mount. Deferred by decision.
- "surge" scenario not built; five shipped.
- Basemap needs internet (labelled, degrades cleanly).
- The kiosk skin (§9c), IVR and Bhashini remain Phase 2.

**Next session:** Phase 1 exit criteria — run the full spine demo three times clean, then
Phase 2. Consider re-verifying compose first since it is the only untested path.

### 2026-08-20 (later still — Phase 1 exit, runbook for the 21 Aug demo)

**Phase 1 exit criteria met.** `make seed && make demo-check` three times consecutively
on `dev-local`, 8/8 every run: `OPTIMAL` in 156 / 196 / 164 ms, 39 patients moved,
39–41 WhatsApp/SMS outbox rows (the SMS ones are WhatsApp failures falling back). The
re-seed between rounds is not optional — the override is sticky, so round 2 would start
against an empty clinic.

**demo-check went 7/7 → 8/8**, because two of the five hops in the exit criterion were
not actually being checked:

- the notification assertion was a bare `count(*)`, which any booking confirmation would
  satisfy; it is now scoped to the reschedule templates on WHATSAPP/SMS and compared
  against the number of patients who were holding appointments.
- "patient PWA shows new slot" was not checked at all. It now captures a real patient of
  HP-DOC-1001 before the replan and asserts the patient app is served her new slot
  afterwards. First version failed three runs straight: a move writes a **new**
  appointment row and marks the old one `RESCHEDULED`, so the old id is gone from the
  queue. Following `rescheduled_from` was the fix — the spine was fine, the assertion
  was wrong.

**Found while writing the runbook: the PWA has no queue-position screen.** The endpoints
exist (`/me/queue`, `/pwa/my-queue/{id}`), the i18n strings exist, nothing renders them.
Not built tonight — it is `frontend/` work needing DESIGN.md §9b, on the eve of a demo.
Noted in 1C, in HANDOFF gaps and in the runbook, which tells the presenter to show the
notification instead. That is the honest artefact anyway: real Hindi naming the
replacement doctor and the new token.

**`infra/demo-script.md` rewritten** for 1C/1D/OTP. It described the M1 presence layer
and still carried a "not built yet" section listing appointments, CP-SAT, patient
channels and the network map — all shipped — which would have had the presenter
disclaiming working features. Now four parts (presence → allocation → access → command
centre), 19 steps, with a route table, the staff-token snippet the old file used but
never defined, and the pre-stage ritual (`make seed && make demo-check`, 8/8 or don't
start). Every command in it was executed against the running stack this session: OTP
request → code out of the outbox → verify → `/me/queue`, the three-turn WhatsApp flow
(booked token 32), the alerts payload, and the Vite dev proxy — `PatientLogin` fetches
`/api/v1/...` relative, so patient login could have been broken in the browser while
every curl passed. It forwards.

**Housekeeping:** HEAD was already two commits past what HANDOFF records (`d656c79`, not
`e4e6a01`). The PRD PouchDB→CouchDB line was hand-edited by the owner and is committed
separately. Compose (`make dev`) is still unverified and is now the mandatory first item
before Phase 2.

**Next session:** re-verify `make dev` on compose, then Phase 2 from the top —
IVR adapter (Exotel, mock telephony).

### 2026-08-21 (compose re-verified, Phase 2 opens with IVR)

**`make dev` is verified.** Four containers up, `libgomp1` installs, both ML artifacts
load through `../ml:/ml:ro` (`metrics/models` → `loaded: true`), alembic runs to `0003`,
login works, `make demo-check` 8/8 against the containers (`OPTIMAL` 233 ms). Two things
the next session needs: **stop brew postgres and redis first**, because compose publishes
5432/6379 as well and will not bind otherwise; and the first build pulls ~500 MB and
takes ~10 minutes, because xgboost drags in `nvidia-nccl-cu12` on linux. The `.venv`
anonymous volume makes every build after that fast.

**Found by running it: `demo_check.py`'s `psql()` swallowed failures.** It assumed the
trust auth a local brew postgres gives, and compose's wants a password — so every query
returned `""` and the first one surfaced ninety lines later as an unpack error. It now
passes `PGPASSWORD` and raises with psql's own stderr. A guard that fails silently is
worse than no guard.

**Phase 2, item 1: IVR (Exotel, mock telephony) — done.** `POST /channels/ivr/webhook`
takes the provider's `CallSid`/`From`/`Digits` payload; `adapters/ivr_mock.py` is the
only thing that knows those names, and hands the flow a `CallTurn`. The keypad flow
lives beside the WhatsApp one in `channels.py` and books through the same
`services/booking.py` — a call is a third way to collect arguments, not a third booking
implementation.

Three decisions worth keeping:

- **Three options per menu, not five.** WhatsApp lists five departments because the
  patient can scroll back. A caller cannot, and nobody holds five spoken options in
  their head.
- **State before intent, again.** Every IVR input is a digit, so `1` means "book" at the
  menu and "option one" while choosing. That is the same bug the WhatsApp flow was
  written around, in voice form, and it has its own test.
- **Silence replays the prompt and moves nothing.** The session stores the last thing
  said; an empty or non-digit press replays it. Clearing state there is how a caller
  ends up indexing a list they can no longer hear.

No `ivr_real.py` (the skill says real second, and only with credentials) and no
outbound `place_call` — that is its own PLAN item. `Channel.IVR` was already in the
enum, so no migration.

**Verified end to end, not just in tests:** `simulators/ivr_call.py 9823872276 1 1 1`
against the running stack books a real appointment with `channel=IVR` and lands a
`booked` receipt in the outbox; the same call from a Hindi-speaking patient's number is
answered in Hindi, chosen from her record rather than by asking her to pick a language.
122 backend tests, 12 frontend, lint clean, demo-check 8/8. The runbook has it as §15.

**Two bugs found by review after the tick, both fixed with regression tests.** The
session stored *the last thing said* rather than the last clean prompt, so a caller who
pressed a wrong key twice heard "Sorry, I did not get that" twice, three times for three
— the apology accumulated. And an unparseable caller id (`From: unknown`, a withheld
number) raised `AdapterError` straight out of the route as a 500, in the one feature
whose adapter docstring says callers degrade rather than crash. It now answers, says why,
and hangs up: a provider needs a 200 with something to play. `_upcoming()` also grew a
`spoken` form — the text version feeds em-dashes to a TTS engine and offers five items
where three is the ceiling. 124 backend tests.

**Next session:** Phase 2 item 2 — Bhashini voice booking (constrained intent flow,
mock mode + sandbox).

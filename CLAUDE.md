# Swasthya-Setu

AI-driven doctor availability & appointment allocation system for Himachal Pradesh hospitals.
Smart India Hackathon 2026 — Team ALTAIR. Grand Finals: December 2026.

**New session? Read `docs/HANDOFF.md` first — it is the 2-minute catch-up.**

**Read `docs/PRD.md` before building any feature. Read `docs/PLAN.md` at the start of every session and tick checkboxes as you complete items. Read `docs/DESIGN.md` before building anything in `frontend/`. Update the Session Log at the bottom of PLAN.md before ending every session.**

## What this system is

A hospital network platform with three pillars:
1. **Presence** — know in real time which doctors are actually available (multi-signal fusion: BLE / RFID / face kiosk / Wi-Fi / roster).
2. **Allocation** — optimize appointments and queues against real availability (OR-Tools CP-SAT + XGBoost predictions).
3. **Access** — let any patient book through any channel (PWA, WhatsApp, IVR, SMS, voice, kiosk), plus a command-center dashboard for administrators.

## Monorepo layout

```
backend/       FastAPI app (Python 3.11). All business logic, REST + WebSocket.
frontend/      React PWA (Vite). Patient app + command center dashboard.
ml/            Training scripts + committed model artifacts (XGBoost, Prophet).
simulators/    Software simulators for every hardware/external signal source.
infra/         docker-compose.yml, migrations config, seed scripts.
docs/          PRD, PLAN, ARCHITECTURE, SCHEMA. Source of truth.
```

## Stack — fixed decisions, do not re-litigate

- Backend: **FastAPI** (not Flask/Django), SQLAlchemy 2.x + Alembic, Pydantic v2
- DB: **PostgreSQL 16**. Cache/pubsub: **Redis 7**. PWA offline outbox: localStorage + REST replay (ARCHITECTURE D23 — PouchDB/CouchDB retired)
- Frontend: **React 18 + Vite PWA**, Tailwind, Leaflet for maps
- Optimization: **Google OR-Tools CP-SAT** (never hand-rolled heuristics)
- ML: **XGBoost** (wait time, no-show), **Prophet** (footfall forecast) — load committed artifacts from `ml/artifacts/`, never train at runtime
- Realtime: FastAPI WebSockets + Redis pub/sub
- Everything runs via `docker compose` from `infra/`

## Commands

```
make dev          # docker compose up full stack (hot reload)
make demo         # seeded demo day: hospitals, doctors, patients, scripted scenario
make test         # pytest (backend) + vitest (frontend)
make migrate      # alembic upgrade head
make seed         # load seed/demo data only
make lint         # ruff + black (py), prettier + eslint (js)
```

If a make target doesn't exist yet, creating it is part of Phase 0.

## Iron rules

1. **Simulator-first.** No feature may require physical hardware or a live external API to demo. Every signal source and every integration must work in `MOCK_MODE`. See `.claude/skills/signal-simulator/` and `.claude/skills/integration-adapter/`.
2. **Adapters for all external services.** Bhashini, WhatsApp Cloud API, Exotel, MSG91, ABDM, e-RaktKosh, OSRM — always behind an adapter interface with a per-service `*_MOCK_MODE` env flag. Never call a vendor SDK from business logic.
3. **Tiers are law.** Tier 1 features must be flawless before Tier 2 work starts. See PRD §Tiers.
4. **Demo is a product feature.** `make demo` must always work on a clean checkout with no internet. If a change breaks the demo, fixing it is priority zero.
5. **Real data where promised.** e-RaktKosh, HMIS footfall, HP road network, 110k-appointment benchmark — ingest per `docs/PRD.md §Data`. If real data is unavailable, generate synthetic data with the same schema and label it synthetic in the UI.
6. **No secrets in code.** Everything via env vars; keep `.env.example` current.

## NEVER BUILD (Tier 3 — slides only)

Do not implement, scaffold, or stub any of these, even if asked in passing. They exist only as roadmap slides: full ABDM production integration, live eSanjeevani interop, live 108 dispatch integration, e-Hospital write-back, national-scale multi-state rollout features, drone/telemedicine extensions, payment/insurance processing, Aadhaar-based auth, staff HR/payroll modules, pharmacy inventory, lab (LIS) integration, ambulance fleet tracking beyond Golden Hour routing demo, patient EHR beyond appointment history, multilingual support beyond Hindi + English (+ constrained Bhashini voice), federated learning, blockchain anything.

If a request seems to require one of these, stop and flag it in chat instead of building.

## Conventions

- Python: type hints everywhere, ruff + black, `snake_case`; routers thin, logic in `services/`
- API: REST under `/api/v1/`, WebSocket events documented in `docs/ARCHITECTURE.md §Events`; every endpoint has a Pydantic response model
- React: function components + hooks, TanStack Query for server state, no Redux
- UI: ALL frontend work follows `docs/DESIGN.md` (MediCore design language). Use the defined CSS tokens / Tailwind theme — never inline hex colors, ad-hoc spacing, or new fonts. Status colors come from DESIGN.md §9d semantic tokens only. Respect the per-surface rules (§9a command center, §9b PWA, §9c kiosk): heavy flair (cursor, veil, grain, blur) is command-center-only
- DB: schema changes only via Alembic migrations; `docs/SCHEMA.md` updated in the same commit
- Tests: every service function gets a unit test; every Tier 1 flow gets one end-to-end test
- Commits: `feat|fix|chore(scope): message` — small and frequent

## Workflow every session

1. Read `docs/PLAN.md` → find current phase and next unchecked item.
2. Read the relevant PRD section for that item. Touching `frontend/`? Also read `docs/DESIGN.md` (at minimum §9).
3. Build → test → `make lint` → tick the checkbox → append to Session Log.
4. When a feature is done, run `/defend <feature>` to generate its judge Q&A entry.

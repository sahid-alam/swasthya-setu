# Handoff — where the build is

Written 2026-08-20, updated 2026-08-21. **Read this once, then work from `docs/PLAN.md`.**
Everything below is state a fresh session cannot infer from the code in reasonable time.

## Status

**Phase 0 and Phase 1 are complete, and Phase 2 has started.** 33 of 48 plan items
ticked; the 15 remaining are the rest of Phase 2 (Tier 2 modules) and Phase 3.

- 122 backend tests, 12 frontend tests, `make lint` clean, suite stable across repeat runs
- `make demo-check` is **8/8** — that is the Iron Rule 4 guard, run it after anything
  touching the spine

**Phase 1 exit is met** (2026-08-20): the spine demo ran clean 3× consecutively on
`dev-local`. `make seed` before each run — the override is sticky, so round 2 starts
with an empty clinic otherwise.

## Run it

```bash
brew services start postgresql@17 && brew services start redis
make install bootstrap-local migrate seed

# backend (SIM_SPEED=12 makes decay visible in ~25s instead of ~5min)
cd backend && DATABASE_URL="postgresql+asyncpg://setu:setu@localhost:5432/swasthya" \
  JWT_SECRET=dev-secret-key-long-enough-for-hs256 \
  PRESENCE_SWEEP_SECONDS=5 SIM_SPEED=12 .venv/bin/uvicorn app.main:app --port 8000

cd frontend && npm run dev      # http://localhost:5173
```

Staff login **9418000001 / setu-admin**. Patient login is `/patient` (phone OTP; the code
appears in the mock outbox at `GET /api/v1/notifications`).

`infra/demo-script.md` is the presenter runbook — every command in it was executed, not
written from memory.

`make dev` (docker compose) is verified as of 2026-08-21 — four containers, artifacts
loaded through the `/ml` mount, `demo-check` 8/8 against them. **Stop brew postgres and
redis first**, compose publishes 5432/6379 too, and the first build pulls ~500 MB. The
demo itself runs on `dev-local`: seconds to start instead of minutes.

## What exists

| Area | State |
|---|---|
| Presence engine (M1) | Signal ingestion, multi-signal fusion with decay, face kiosk matching, admin override, evidence trail |
| Allocation (M2) | CP-SAT replan, worst case 176 ms vs a 5 s budget; every solve writes `plan_runs` |
| ML | No-show on the **real** 110k dataset (AUC 0.735); wait-time on **synthetic** clinic days (MAE 15.0 vs naive 27.3), labelled SYNTHETIC everywhere |
| Access (M3) | Channel-agnostic booking, WhatsApp guided flow, SMS, IVR keypad booking (mock telephony), notification fan-out with a real outbox, patient PWA in Hindi/English with an offline queue, phone-OTP login |
| Command centre (M4) | Presence board with evidence drawer, queues with predicted waits, alerts, Leaflet map, scenario trigger panel |
| Simulators | `simulators/` — personas, run_day, scenario, roster_feed, face_mock, ivr_call. External HTTP clients, never touch the DB |

## The five things that will waste your time if you do not know them

1. **`str.replace` patch scripts silently no-op** when black has reformatted the target.
   This bit five times, once leaving a half-applied change that typechecked and called the
   wrong endpoint. **Use the Edit tool for surgical edits** — it fails loudly.
2. **`TestClient` deadlocks** if you make an HTTP call inside a `websocket_connect` block.
   Publish to Redis directly instead (see `tests/test_events.py`).
3. **Every WS test must wait for the `ws.ready` first frame.** Subscribing is async;
   counting subscribers is wrong because a running dev server is also a subscriber.
4. **`JSONB` stores Python `None` as JSON `null`, not SQL NULL.** Use
   `JSONB(none_as_null=True)` on any nullable JSONB column.
5. **Restart uvicorn after a migration** — asyncpg caches prepared statements and throws
   `InvalidCachedStatementError` on the first request against a changed schema.

Also: tests share one database, so anything mutating appointments must build its own
fixture state (`clinic_list`, `fresh_badge` in `tests/conftest.py`) rather than leaning on
the seed or on test order.

## Decisions already made — do not re-litigate

`docs/ARCHITECTURE.md` has the full table (D1–D25). The ones most likely to be
second-guessed:

- **D15** — the roster decides when slots *exist*; only a **confident** presence state
  removes them. A low-confidence state *is* the roster, so acting on it would be the
  system arguing with itself.
- **D12/D13** — fusion scores max-per-location, not sum, and recency picks the current
  sighting while trust only gates belief. Summing made movement undetectable.
- **D23** — PWA outbox is localStorage + REST replay. PouchDB and CouchDB are retired.
- **D25** — patient auth is phone OTP on the existing SMS adapter and JWT. No new service.
- **Supabase: closed, no.** Asked and answered.

## Honest gaps — say these out loud, do not paper over them

- **Basemap tiles need internet.** Verified offline: tiles fail, markers still place, and
  the map labels itself "Basemap offline — positions are real".
- **Wait-time model is trained on synthetic data.** It says so in the manifest, the metrics
  file and the API. Never describe it as trained on real data.
- **FCFS comparison does not say what we wanted.** With spare capacity CP-SAT does *not*
  reduce mean waiting time (23.1 vs 22.7 min — marginally worse); it changes *who* waits.
  In a busy department it is 71.8 vs 147.8 min. The claim is **"the right people wait
  less"**, never "everyone waits less".
- **The PWA has no queue-position screen.** `/api/v1/me/queue` serves position and
  predicted wait, `demo-check` asserts on it, the i18n strings exist — nothing renders
  them. What a patient actually sees after a reschedule is the notification.
- **"surge" scenario not built** — five scenarios shipped.
- Kiosk skin (§9c), Bhashini, outbound TTS, beds, referrals, blood, Prophet, Golden
  Hour: the rest of Phase 2, untouched. IVR is done (mock telephony; no `ivr_real.py`
  until Exotel credentials exist).

## Next

Phase 2, from the top of `docs/PLAN.md`.

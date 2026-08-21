# Handoff — where the build is

Written 2026-08-20, rewritten 2026-08-21. **Read this once, then work from `docs/PLAN.md`.**
Everything below is state a fresh session cannot infer from the code in reasonable time.

## Status

**Phase 0 and Phase 1 are complete; Phase 2 is well under way.** 38 of 54 plan items
ticked. Migrations are at `0006`.

- **182 backend tests, 13 frontend tests**, `make lint` clean, suite stable across repeat runs
- `make demo-check` is **8/8** — the Iron Rule 4 guard; run it after anything touching the spine
- **The next session is UI work.** Backend paused mid-Phase-2; Bhashini is the next
  unchecked item when it resumes.

## Run it

```bash
# compose publishes 5432/6379 too — `docker compose -f infra/docker-compose.yml down`
# first, or these will not bind
brew services start postgresql@17 && brew services start redis
make install bootstrap-local migrate seed

# backend (SIM_SPEED=12 makes decay visible in ~25s instead of ~5min)
cd backend && DATABASE_URL="postgresql+asyncpg://setu:setu@localhost:5432/swasthya" \
  JWT_SECRET=dev-secret-key-long-enough-for-hs256 \
  PRESENCE_SWEEP_SECONDS=5 SIM_SPEED=12 .venv/bin/uvicorn app.main:app --port 8000

cd frontend && npm run dev      # http://localhost:5173
```

Staff login **9418000001**; the password is printed by `make seed` and kept in the
gitignored `.admin-password` (or set `ADMIN_PASSWORD` in `.env`). Nothing in this repo
contains it. Patient login is `/patient` — phone **or** email OTP; in mock mode the code
appears in the outbox at `GET /api/v1/notifications`.

`make dev` (docker compose) is verified and 8/8, but the demo runs on `dev-local`:
seconds to start instead of minutes. `infra/demo-script.md` is the presenter runbook —
every command in it was executed, not written from memory.

## What exists

| Area | State |
|---|---|
| Presence (M1) | Signal ingestion, multi-signal fusion with decay, face kiosk matching, admin override, evidence trail |
| Allocation (M2) | CP-SAT replan, worst case 176 ms against a 5 s budget; every solve writes `plan_runs` |
| ML | No-show on the **real** 110k dataset (AUC 0.735); wait-time on **synthetic** clinic days, labelled SYNTHETIC everywhere |
| Access (M3) | One booking service behind every channel: PWA, WhatsApp, SMS, **Telegram**, IVR keypad, Vapi voice agent, staff desk |
| Command centre (M4) | Presence board with evidence drawer, queues with predicted waits, alerts, Leaflet map, scenario panel, voice-call button |
| Frontend | `routes/`: PresenceBoard, Queues, Alerts, NetworkMap, Scenarios, Dashboard, Book, Login, PatientLogin, DevUI. `components/`: Shell (dock), VoiceCall, `ui/` primitives |
| Simulators | personas, run_day, scenario, roster_feed, face_mock, ivr_call, vapi_call. External HTTP clients, never touch the DB |

## Live channels — what is real and what is mocked

Mock is the default everywhere. Iron Rule 4 was reworded on 2026-08-21 to *the demo must
survive offline*: live mode is welcome, the price is a mock that is the default, one
`<SERVICE>_MOCK_MODE` switch, and `demo-check` exercising the mock path.
`GET /api/v1/health` reports which adapters are mocked.

| Channel | Live? |
|---|---|
| **Telegram** | **Verified end to end** on a real handset — OTP, booking, cancellation, all `mock=false`. @Swasthya_Setu_bot |
| **Email** | **Verified through Gmail** — OTP and booking confirmation, HTML built from DESIGN.md tokens. A first send lands in spam; that is sender reputation, not a bug |
| **Phone OTP (2Factor voice)** | **Verified live** — a real call reads the code out. `SMS_PROVIDER=2factor-voice` + `TWOFACTOR_API_KEY`. OTP-only: it delivers digits, not sentences |
| **Vapi** | Tools verified over the public internet via `make tunnel`. The browser button needs `VITE_VAPI_PUBLIC_KEY` + `VITE_VAPI_ASSISTANT_ID` and is **unproven** |
| WhatsApp | Code complete, **parked** on Meta template approval |
| SMS text (2Factor) | Built (`SMS_PROVIDER=2factor-sms`) and **off**: it reports DELIVERED and is still carrier-filtered. That is India's DLT registration, not our code — one env value once the sender ID clears |
| SMS text (Android gateway) | Code complete, **unverified**: the handset answered no ARP on the LAN and its Cloud token is `NotRegistered` |
| IVR | Mock telephony by design — no Exotel account |

**Where a login code actually goes.** Email login → email. Phone login → a linked
Telegram chat if there is one (free, instant, and the patient linked it for exactly
this), otherwise whatever `SMS_PROVIDER` is — a 2Factor voice call when live, the mock
outbox otherwise. Always **exactly one channel**, never a fan-out: a code sent to two
places is a code delivered to whoever holds either one. `via: "sms"` forces the fallback.

**Live SMS and voice are fenced** (CLAUDE.md §Conventions): 30/day and 5/minute counted
in Redis by `adapters/sms_fence.py` and shared by every provider, tests always run mock
whatever `.env` says, and **`demo-check` refuses to run at all while SMS is live** —
expect that and flip `SMS_MOCK_MODE=true` to verify the spine.

## The things that will waste your time if you do not know them

1. **`.env` comments must be on their own line.** This parser keeps everything right of
   the `=`, so a trailing `# comment` becomes part of the value. That silently broke
   three integrations in one day. Config now strips whitespace from credentials and
   parses anything address-shaped with `parseaddr`, but the file itself is the real fix.
2. **`str.replace` patch scripts silently no-op** when black has reformatted the target.
   **Use the Edit tool for surgical edits** — it fails loudly.
3. **Never run `black` on a path outside `backend/`** in the same invocation as backend
   files: it resolves the common root, misses `backend/pyproject.toml`, and reformats at
   88 instead of 100. The magic trailing comma then makes that stick.
4. **`TestClient` deadlocks** if you make an HTTP call inside a `websocket_connect`
   block. Publish to Redis directly (see `tests/test_events.py`).
5. **Every WS test must wait for the `ws.ready` first frame.** Subscribing is async.
6. **`JSONB` stores Python `None` as JSON `null`, not SQL NULL.** Use `JSONB(none_as_null=True)`.
7. **Restart uvicorn after a migration** — asyncpg caches prepared statements.
8. **`make seed` truncates `patients`**, destroying any live Telegram link and the demo
   patient's phone and email. Set `DEMO_PATIENT_PHONE` and `DEMO_PATIENT_EMAIL` in `.env`
   so a re-seed restores them; the Telegram chat still needs one re-tap of Share.
9. **`pkill -f uvicorn` can leave a stale listener on :8000**, and the next server starts
   without ever binding — so your new env vars appear to be ignored. Kill by port:
   `lsof -nP -iTCP:8000 -sTCP:LISTEN -t | xargs kill -9`.
10. **The rate fence is real Redis state, shared by every provider.** Tests must never
   spend it; a day of testing once exhausted 30/day and the suite began failing by the
   calendar rather than by the code.

Tests share one database, so anything mutating appointments must build its own fixture
state rather than leaning on the seed or on test order.

## Decisions already made — do not re-litigate

`docs/ARCHITECTURE.md` has the full table (D1–D30). Most likely to be second-guessed:

- **D26 — authentication stays ours.** JWT + phone/email OTP. No Supabase, Clerk, Better
  Auth or any hosted identity provider. **Closed.** A hosted login cannot be mocked and
  cannot run at a venue with no internet.
- **D28 — Vapi reaches us through a `cloudflared` quick tunnel, not a deploy.** One
  command, no account, demo stays laptop-local. It publishes the whole backend, so it is
  demo-time only.
- **D15** — the roster decides when slots *exist*; only a **confident** presence state
  removes them.
- **D12/D13** — fusion scores max-per-location, not sum; recency picks the current
  sighting while trust only gates belief.
- **D23** — PWA outbox is localStorage + REST replay. PouchDB and CouchDB are retired.
- **Supabase: closed, no.** Asked and answered.

## Honest gaps — say these out loud, do not paper over them

- ~~The PWA has no queue-position screen.~~ **Built 2026-08-21** — `/my-queue`
  (`routes/MyQueue.tsx`), linked from the booking confirmation. A reschedule is now
  visible on a screen, not only in the notification.
- **The Vapi call button has never been used.** Gated on `VITE_VAPI_*`; unset, it says so
  and Vite drops the 300 kB SDK from the bundle entirely.
- **Wait-time model is trained on synthetic data.** It says so in the manifest, the
  metrics file and the API. Never describe it as trained on real data.
- **FCFS comparison does not say what we wanted.** With spare capacity CP-SAT does *not*
  reduce mean waiting time (23.1 vs 22.7 min — marginally worse); it changes *who* waits.
  In a busy department it is 71.8 vs 147.8 min. The claim is **"the right people wait
  less"**, never "everyone waits less".
- **Basemap tiles need internet.** Verified offline: tiles fail, markers still place, and
  the map labels itself "Basemap offline — positions are real".
- **"surge" scenario not built** — five scenarios shipped.
- Kiosk skin (§9c), Bhashini, outbound TTS, beds, referrals, blood, Prophet, Golden
  Hour: the rest of Phase 2, untouched.

## Next

**UI work.** Read `docs/DESIGN.md` before touching `frontend/` — at minimum §9, which
splits the surfaces. §9a command centre gets the full treatment (dark dock, veil, grain,
custom cursor, and live-state text ≥15px because judges watch from 3 m). §9b patient PWA
gets **none** of the flair — no custom cursor, no blur, no backdrop-filter, all of which
are jank on a budget Android — plus 48px touch targets and Hindi first. Never inline a
hex: the tokens live in `frontend/src/styles/tokens.css` and mirror DESIGN.md §1.

Backend resumes at Bhashini, the next unchecked item in `docs/PLAN.md`.

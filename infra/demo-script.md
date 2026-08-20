# Presenter runbook — Presence engine (M1)

Phase 1A scope. No Docker, no hardware, no internet needed.

## Start (three terminals, ~30 seconds)

```bash
# 1. services (once per machine)
brew services start postgresql@17 && brew services start redis
make bootstrap-local          # creates the setu role + swasthya database

# 2. backend.  SIM_SPEED=12 compresses time so decay is visible in ~25s instead of
#    ~5 minutes; the fusion maths is identical, only the tau constants scale.
cd backend
DATABASE_URL="postgresql+asyncpg://setu:setu@localhost:5432/swasthya" \
JWT_SECRET=dev-secret-key-long-enough-for-hs256 \
PRESENCE_SWEEP_SECONDS=5 SIM_SPEED=12 \
.venv/bin/uvicorn app.main:app --port 8000

# 3. frontend
cd frontend && npm run dev
```

Reset to a clean stage at any point with `make migrate seed` (deterministic —
the same 3 hospitals, 30 doctors and 200 patients every single time).

Open <http://localhost:5173> and sign in: **9418000001 / setu-admin**

> **Expect rows to fade back to grey.** At `SIM_SPEED=12` a signal ages out in ~25
> seconds, so a doctor you "arrived" earlier will be grey again by the time you reach
> step 5. That is the product working, not breaking — say so, or just re-run
> `arrives` for that badge. Drop to `SIM_SPEED=4` if you want states to linger and
> you are willing to wait ~75s for the decay step.

## The click path

Keep the board on screen the whole time. It is WebSocket-driven — you never refresh.

### 1. Open on the honest board (20s)

Everyone reads **grey "Present In Dept — ROSTER ONLY 30%"**.

> "This is what every existing system shows you: the roster. We are showing you that
> we have *no idea* whether these doctors are actually there. Grey means we're
> repeating paperwork, not reporting reality."

### 2. A doctor arrives (30s)

```bash
backend/.venv/bin/python simulators/scenario.py arrives HP-DOC-1001
```

Row turns green, confidence climbs, a **just changed** chip appears, zone fills in.
Nothing was clicked.

> "That's a badge at the gate and then a beacon in his own OPD. Same REST endpoint
> real hardware posts to — the simulator is just a client."

### 3. Walking from OPD to surgery — *PRD M1 accept #1* (30s)

```bash
backend/.venv/bin/python simulators/scenario.py walk_to_surgery HP-DOC-1006
```

State flips **In department → In surgery** on the theatre-door tap.

Click **evidence** on that row:

> "Every state has a receipt. RFID saw him at IGMC-SML-OT, score 0.90, zero seconds
> ago. Ninety minutes of OPD pings didn't hold him in place, because a person is in
> one location — sightings compete, they don't accumulate."

### 4. The roster is wrong — *PRD M1 accept #4* (40s)

```bash
backend/.venv/bin/python simulators/roster_feed.py HP-DOC-1011 LEAVE   # HMIS says away
backend/.venv/bin/python simulators/scenario.py arrives HP-DOC-1011    # but he's here
```

Board shows **Present In Dept**; the evidence drawer says *Roster says On leave*.

> "This is the answer to 'why not just an attendance app'. The paperwork says he's on
> leave. The building says otherwise. We believe the building, and we show you both."

### 5. The beacon battery dies — *PRD M1 accept #2* (40s)

```bash
backend/.venv/bin/python simulators/scenario.py beacon_dead HP-DOC-1003
```

Watch the row for ~25 seconds: confidence falls 0.64 → 0.41 → 0.34 and the chip goes
**grey / ROSTER ONLY**. (Verified timing at `SIM_SPEED=12`.)

> "Silence is information. It never silently stays green — it decays back to a
> labelled guess."

### 6. Admin override (20s)

```bash
backend/.venv/bin/python simulators/scenario.py doctor_absent HP-DOC-1004
```

> "A phone call at 9 AM. An override outranks every sensor — a badge left on a desk
> can't argue with it — and the trail records who set it and why."

### 7. Face kiosk + privacy (30s)

```bash
backend/.venv/bin/python simulators/face_mock.py HP-DOC-1005 IGMC-SML-LOBBY   # matches
backend/.venv/bin/python simulators/face_mock.py HP-DOC-1001                  # refuses
```

> "Check-in is voluntary. Only doctors who enrolled are matchable, we store the
> embedding and never an image, and the public API never serves embeddings back."

## Optional: a whole day in two minutes

```bash
backend/.venv/bin/python simulators/run_day.py --hospital IGMC-SML --minutes 2 --speed 240 --seed 42
```

~1000 signals; doctors arrive, hold OPD, go on rounds, enter theatre. `--seed 42`
means every rehearsal is identical.

## If something breaks

| Symptom | Fix |
|---|---|
| Board empty / "Reconnecting…" | Token expired. Sign out and back in (JWT secret changed between restarts). |
| `Connection refused` from a simulator | Backend isn't up on :8000. |
| Everything grey and nothing moves | `make seed` again — day-0 rosters are anchored to seed time. |
| Port 5173 taken | Vite prints the port it actually used; use that one. |

## What is NOT built yet (say so if asked)

Appointments, the CP-SAT optimizer, patient channels and the network map are Phase 1B–1D.
This demo is the presence layer only — the thing everything else is scheduled against.

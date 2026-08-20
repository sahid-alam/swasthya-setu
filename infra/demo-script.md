# Presenter runbook — the spine, end to end

Phase 1 scope: presence (M1) → allocation (M2) → access (M3) → command centre (M4).
No Docker, no hardware, no internet needed.

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

**Before you walk on stage, run the guard:**

```bash
make seed && make demo-check          # 8/8 PASS, about six seconds
```

It walks the whole spine headless: presence flip → CP-SAT replan → notification
fan-out → what the patient app is served. If it is not 8/8, do not start; the number
it prints for `plan_runs` is the same number you are about to claim on stage.
(Verified 3× consecutively on 2026-08-20: OPTIMAL in 156 / 196 / 164 ms, 39 patients
moved each time.)

Several commands below use a staff token. Get one once, in the terminal you will
type into:

```bash
TOK=$(curl -s -X POST localhost:8000/api/v1/auth/token \
  -d 'username=9418000001&password=setu-admin' | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')
```

### Where things are

| Route | What |
|---|---|
| `/login` | staff sign-in — **9418000001 / setu-admin** |
| `/` | presence board (the opening shot) |
| `/queue` | queues with predicted waits |
| `/alerts` | roster-vs-presence mismatches, overflow, pending rebookings |
| `/map` | Leaflet network map |
| `/scenarios` | the presenter's remote control (admin only) |
| `/events` | raw WebSocket feed, if a judge wants the plumbing |
| `/patient` | patient sign-in by phone OTP |
| `/book` | the patient app itself |

Open <http://localhost:5173> and sign in as staff. Keep a second browser window
(or a phone-sized window) on `/patient` for Part 3.

> **Expect rows to fade back to grey.** At `SIM_SPEED=12` a signal ages out in ~25
> seconds, so a doctor you "arrived" earlier will be grey again by the time you reach
> step 5. That is the product working, not breaking — say so, or just re-run
> `arrives` for that badge. Drop to `SIM_SPEED=4` if you want states to linger and
> you are willing to wait ~75s for the decay step.

## Part 1 — presence (M1)

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

## Part 2 — allocation (M2)

Presence is only worth building if something acts on it. This is that something.

### 8. A doctor calls in sick at 9 AM with 40 booked patients — *PRD M2 accept #1* (60s)

Show the clinic list first:

```bash
curl -s localhost:8000/api/v1/scheduling/clinic -H "Authorization: Bearer $TOK" \
  | python3 -m json.tool | head -20
```

Then make the call:

```bash
backend/.venv/bin/python simulators/scenario.py doctor_absent HP-DOC-1001
```

> "Nobody clicked 'reschedule'. The presence change *is* the trigger. Thirty-nine
> patients were re-seated across his colleagues in about two hundred milliseconds, and
> the plan and the presence board can't disagree because they committed together."

Then show the receipt:

```bash
curl -s "localhost:8000/api/v1/scheduling/plan-runs?limit=1" -H "Authorization: Bearer $TOK"
```

`solver_status: OPTIMAL`, `duration_ms`, `moved_count`. Every solve this system has ever
run is in that table — that is the "<5 seconds" claim with evidence, not a slide.

### 9. "How do you know the predictions are any good?" — *PRD M2 accept #2* (40s)

```bash
curl -s localhost:8000/api/v1/metrics/models -H "Authorization: Bearer $TOK"
```

> "No-show is trained on the real public 110,527-appointment dataset. ROC-AUC 0.735,
> Brier 0.143 against a 0.161 base rate. That is a real number, not a good one — anyone
> showing you 0.95 on this dataset is leaking a feature.
> The wait-time model has no real dataset to train on, so it is trained on simulated
> clinic days and the API says SYNTHETIC in the response. It beats the arithmetic your
> reception desk already does — 15 minutes of error against 27."

### 10. "Why CP-SAT and not first-come-first-served?" — *PRD M2 accept #3* (60s)

```bash
cat ml/artifacts/fcfs_comparison.json | python3 -m json.tool
```

**Say this honestly, it is the strongest thing in the deck:**

> "When there is spare capacity, our optimiser does *not* make people wait less. Mean
> displacement is 23 minutes against FCFS's 22 — we are marginally worse. What changes
> is *who* waits: a referred patient waits zero minutes instead of twenty-five.
> When the department is genuinely busy — which is every real day in Himachal — mean
> displacement is 72 minutes against 148, and first-come-first-served ends up turning
> away referred patients entirely because it never looks at why they were referred.
> The claim is that the right people wait less. Not that everyone does."

## Part 3 — access (M3)

This is the half of the system that faces a patient in Kinnaur, not an administrator
in Shimla. Run it in a phone-sized second window.

### 11. A patient signs in with a phone number and nothing else (40s)

Open `/patient`. It comes up in **Hindi** first, with a one-tap language switch.
Enter **9868553803** (Priya Chauhan — a seeded patient whose language is Hindi).

The code goes out over the SMS adapter, which is in mock mode, so it lands in the
outbox instead of on a handset:

```bash
curl -s "localhost:8000/api/v1/notifications?limit=1" -H "Authorization: Bearer $TOK" \
  | python3 -m json.tool
```

`"template": "otp"`, and the body is real Hindi: *"स्वास्थ्य-सेतु: आपका लॉगिन कोड 594358
है। यह 5 मिनट में समाप्त हो जाएगा।"* Type that code in; you land on `/book`.

> "No password, no Aadhaar, no app-store download. A phone number and a code, on the
> same SMS adapter that already sends the reschedule notices — we did not add an auth
> service to get patient login."

Note the reply to the *request* is deliberately vague — "if that number is registered"
— so the endpoint cannot be used to find out who is a patient.

### 12. Booking, in the patient's own language (30s)

Choose a department, pick a time, and the confirmation names the doctor, the hospital
and the **token number**. Same `/api/v1/booking` the WhatsApp adapter and the staff
desk call — the channel is a skin, not a second system.

### 13. The tunnel between Shimla and Mandi — *PRD M3 accept* (45s)

With `/book` open: DevTools → Network → **Offline**. Book an appointment.

- an amber banner appears: the app says it is offline rather than pretending
- the booking is kept, not lost — the panel shows **1 pending**

Switch the network back on and press **Sync now**. Pending drains to 0 and the
booking is on the server.

> "Rural Himachal is not a place with continuous connectivity. The intent is written
> to the device, replayed over the normal REST API when the signal comes back, and the
> patient never re-types anything. No sync server, no CouchDB — the outbox is
> localStorage and the same endpoint."

### 14. WhatsApp, for the people who will never install anything (40s)

```bash
wa() { curl -s -X POST localhost:8000/api/v1/channels/whatsapp/inbound \
  -H "Authorization: Bearer $TOK" -H 'Content-Type: application/json' \
  -d "{\"from_phone\":\"9823872276\",\"text\":\"$1\"}" | python3 -m json.tool; }

wa book      # -> numbered list of departments,  state: choosing_department
wa 1         # -> numbered list of times,        state: choosing_slot
wa 1         # -> "Confirmed. Token 32."         state: booked
```

> "Three messages, no smartphone app, no data plan beyond WhatsApp. The conversation
> state lives in Redis with a TTL, the adapter is in mock mode, and behind it is the
> exact same booking service the PWA calls. Swapping in the Meta Cloud API is a
> credential, not a rewrite."

### 15. "Did those thirty-nine patients actually get told?" (30s)

This is the payoff of step 8 — go back to it after the replan.

```bash
curl -s "localhost:8000/api/v1/notifications?limit=5" -H "Authorization: Bearer $TOK" \
  | python3 -m json.tool
```

Real messages, in Hindi, naming the replacement doctor and the new token:
*"आपका अपॉइंटमेंट Indira Gandhi Medical College में 20 Aug, 18:58 पर बदल दिया गया है।
अब आपको Dr. Mohan Rana देखेंगे। टोकन 4।"*

> "WhatsApp first, SMS only if WhatsApp fails — a patient reached on WhatsApp does not
> also get an SMS that costs money. The SMS rows you see are the failures falling back,
> and the failures are logged too. This table is the outbox; there is no vendor account
> and no venue internet involved in showing it to you."

And what that patient's own app is served now:

```bash
curl -s localhost:8000/api/v1/pwa/my-queue/<patient_id> -H "Authorization: Bearer $TOK"
```

New doctor, new time, `position` and `predicted_wait_minutes`.

> **Honest note, say it if asked:** the patient's *queue-position screen* is not built —
> the endpoint is, the messages are, and `make demo-check` asserts on it. Show the
> message, not a screen.

## Part 4 — command centre (M4)

### 16. Queues with predicted waits (20s)

`/queue`. Per department, in position order, each with a predicted wait.

> "The wait number is the SYNTHETIC-labelled model from step 9. We would rather show
> you a labelled estimate than an unlabelled one."

### 17. Alerts — the screen an administrator actually leaves open (30s)

`/alerts`:

> "Dr. Rajesh Thakur is rostered but absent — Roster says OPD until 01:28; presence
> says on leave (96% confidence)."

Three kinds: roster-vs-presence mismatch, queue overflow, and patients still pending a
rebooking. Every one names the evidence and the number of patients behind it.

### 18. The network map (20s)

`/map`. Facilities with live status across the HP road network.

> "If the venue has no internet the basemap tiles will not load. The app detects that
> and labels itself **'Basemap offline — positions are real'** — the markers, the
> statuses and every number are ours and still correct."

### 19. The remote control (20s)

`/scenarios`, admin only. The five scenarios from Part 1 as buttons: *Doctor arrives*,
*Walk to surgery*, *Beacon battery dies*, *Calls in sick*, *Roster is wrong*.

> "These post to the same public `/signals` endpoint the simulators and real hardware
> use. A demo button that wrote to the database would make the whole demo a lie."

("surge" is not built — five scenarios shipped. Say so if someone asks for a sixth.)

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
| OTP code never appears | It is not sent to a handset. Read it from `/api/v1/notifications` with the staff token — `"template": "otp"`, newest first. |
| Patient app shows staff data | One browser window, two tokens. Use a second window (or private tab) for `/patient`. |
| WhatsApp replies loop back to the menu | The session TTL expired between turns. `wa book` and walk it again. |
| `InvalidCachedStatementError` | You ran a migration against a live backend. Restart uvicorn. |
| Anything at all, before you present | `make seed && make demo-check`. 8/8 or do not start. |

## What is NOT built yet (say so if asked)

Everything above is Phase 1 and it is complete. Phase 2 is untouched: IVR (Exotel),
Bhashini voice booking, outbound TTS reschedule calls, the kiosk skin, bed management,
referral reservations, the e-RaktKosh blood widget, the Prophet footfall forecast, the
Golden Hour router, and the ABDM/eSanjeevani/108/e-Hospital adapter backbone.

The patient queue-position screen (§15) and a "surge" scenario (§19) are the two gaps
inside Phase 1. `make dev` (docker compose) has not been re-verified since the image
gained `libgomp1` and the `../ml` mount — **present from `dev-local`**, which is what
this runbook describes and what was rehearsed.

# Presenter runbook — the spine, end to end

Presence (M1) → allocation (M2) → access (M3) → command centre (M4) → Golden Hour (M8)
and referral reservation (M5). No Docker, no hardware, no internet needed.

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

On a clean machine, `make demo` does all of the seeding in one go — migrations, the
demo day, and the 159 beds and blood stock the Golden Hour and referral beats need.

Reset to a clean stage at any point with `make seed` (deterministic — the same 3
hospitals, 30 doctors, 200 patients and 159 beds every single time).

> **`make seed` truncates `patients`**, which kills a live Telegram link and the demo
> patient's phone and email. Set `DEMO_PATIENT_PHONE` / `DEMO_PATIENT_EMAIL` in `.env`
> so a reseed restores them; the Telegram chat still needs one re-tap of Share. If you
> only want beds and blood back, `make seed-facilities` is additive and touches no
> patient.

**Before you walk on stage, run the guard:**

```bash
make demo-check          # 12/12 PASS, about ten seconds
```

It walks the whole scripted scenario headless: presence flip → CP-SAT replan →
notification fan-out → what the patient app is served → Golden Hour ranking → referral
with a bed reservation. If it is not 12/12, do not start; the number it prints for
`plan_runs` is the same number you are about to claim on stage.

**It no longer needs a `make seed` first.** It picks a doctor from live data — one who
has a clinic AND an available colleague to re-seat it onto — and restores his presence
state and releases its referral hold when it finishes. Verified 3× consecutively on
2026-08-21, 12/12 each, no seed between runs.

Several commands below use a staff token. Get one once, in the terminal you will
type into:

```bash
TOK=$(curl -s -X POST localhost:8000/api/v1/auth/token \
  -d "username=9418000001&password=$(cat .admin-password)" \
  | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')
```

There is no password in this repo. `make seed` prints the staff password and writes it
to the gitignored `.admin-password`; set `ADMIN_PASSWORD` in `.env` if you would rather
choose one.

### Where things are

| Route | What |
|---|---|
| `/login` | staff sign-in — **9418000001**, password from `.admin-password` |
| `/` | presence board (the opening shot) |
| `/queue` | queues with predicted waits |
| `/alerts` | roster-vs-presence mismatches, overflow, pending rebookings |
| `/map` | Leaflet network map |
| `/beds` | bed occupancy per ward (M5) |
| `/referrals` | referral holds with a live expiry countdown (M5) |
| `/golden-hour` | emergency facility ranking (M8) |
| `/impact` | waiting avoided + the CP-SAT vs FCFS chart — the closing screen |
| `/scenarios` | the presenter's remote control (admin only) |
| `/events` | raw WebSocket feed, if a judge wants the plumbing |
| `/patient` | patient sign-in by phone OTP |
| `/book` | the patient app itself |
| `/my-queue` | the patient's own place in the queue |

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

> "No-show is trained on the real public 110,527-appointment dataset — Vitoria, Brazil,
> because no Indian no-show set of that size is public. ROC-AUC 0.735, Brier 0.143
> against a baseline of 0.161, which is what you score by predicting the 20.2% base rate
> for everybody. That is a real number, not a good one — anyone showing you 0.95 on this
> dataset is leaking a feature.
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

**Or by email**, for a handset that drops SMS: tap *Use email instead*. Same screen,
same code, same JWT — the address is looked up case-insensitively and the code goes to
the inbox and nowhere else. `make seed` puts `DEMO_PATIENT_EMAIL` on the first patient,
so this works against an inbox you can actually open; without it, no patient has an
address and the email path answers exactly like an unknown one.

> "One flag — `EMAIL_MOCK_MODE=false` plus an SMTP block — and that same code goes out
> over real Gmail. We keep the mock as the default because a demo that needs the venue's
> internet is a demo that can fail in front of you. That is Iron Rule 4: the thing must
> survive offline, not avoid being live."


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

### 15. A farmer with a feature phone — *PRD M3 accept #1* (45s)

No smartphone, no data, no literacy assumption. Just a phone call.

```bash
backend/.venv/bin/python simulators/ivr_call.py 9823872276 1 1 1
```

Each line is what the caller hears; `1 1 1` is book, first department, first time.
Drop the digits to press them yourself, one at a time.

```
♫ Welcome to Swasthya-Setu. Press 1 to book an appointment. Press 2 to hear your appointments.
♫ Choose a department. Press 1 for General Medicine, Indira Gandhi Medical College. …
♫ Choose a time. Press 1 for 20 August, 19:05, Dr. Mohan Rana. …
♫ Your appointment is confirmed with Dr. Mohan Rana on 20 August, 19:05. Your token number is 5.
```

Now call as a Hindi-speaking patient — the language comes from her record, she is never
asked to choose one:

```bash
backend/.venv/bin/python simulators/ivr_call.py 9868553803 1 1 1
```

> "Three options a menu, not five — a caller has no screen to scroll and cannot hold
> five in their head. The simulator posts the same `CallSid`/`From`/`Digits` payload
> Exotel posts, to the same webhook; swapping in the real line is a credential, not a
> rewrite. And the booking went through the same service the PWA calls, so this
> appointment is on the dashboard next to the others, marked as having come in by
> phone."

The caller has no screen to go back to, so the message is her only record:

```bash
curl -s "localhost:8000/api/v1/notifications?limit=10" -H "Authorization: Bearer $TOK" \
  | python3 -c "import sys,json;rows=[n for n in json.load(sys.stdin) if n['template']=='booked'];print(json.dumps(rows[:1],ensure_ascii=False,indent=2))"
```

### 16. "Did those thirty-nine patients actually get told?" (30s)

This is the payoff of step 8 — go back to it after the replan.

The outbox is newest-first, and by now the login code and the two bookings you just
made sit on top of it — so filter to the reschedule notices rather than raising the
limit and scrolling. (The filter also prints real Devanagari instead of `\uXXXX`.)

```bash
curl -s "localhost:8000/api/v1/notifications?limit=60" -H "Authorization: Bearer $TOK" \
  | python3 -c "import sys,json;rows=[n for n in json.load(sys.stdin) if n['template']=='rescheduled'];print(json.dumps(rows[:3],ensure_ascii=False,indent=2))"
```

Real messages, in Hindi, naming the replacement doctor and the new token:
*"स्वास्थ्य-सेतु: आपका अपॉइंटमेंट Indira Gandhi Medical College में 20 Aug, 18:51 पर बदल
दिया गया है। अब आपको Dr. Deepak Bhardwaj देखेंगे। टोकन 2।"*

> "WhatsApp first, SMS only if WhatsApp fails — a patient reached on WhatsApp does not
> also get an SMS that costs money. The SMS rows you see are the failures falling back,
> and the failures are logged too. This table is the outbox; there is no vendor account
> and no venue internet involved in showing it to you."

And what that patient's own app is served now:

```bash
PID=$(psql -U setu -h localhost -d swasthya -tAc \
  "select patient_id from notifications where template='rescheduled' order by created_at desc limit 1")
curl -s "localhost:8000/api/v1/pwa/my-queue/$PID" -H "Authorization: Bearer $TOK" \
  | python3 -m json.tool
```

New doctor, new time, `position` and `predicted_wait_minutes`.

Then show her the screen, not just the message: `/my-queue` in the patient window.

> "This is what she opens. Her number in the line, how many people are ahead of her as
> dots she can count without reading, and the estimated wait. If we have already moved
> her it says so; if we are still finding her a slot it says *that*, rather than showing
> a confident time we do not have."

> **Honest note:** the wait figure is the SYNTHETIC-trained model from step 9. The screen
> calls it an estimate in the patient's own language rather than wearing a SYNTHETIC chip
> — that chip is a signal for you and the judges, not for someone in a corridor.

## Part 4 — command centre (M4)

### 17. Queues with predicted waits (20s)

`/queue`. Per department, in position order, each with a predicted wait.

> "The wait number is the SYNTHETIC-labelled model from step 9. We would rather show
> you a labelled estimate than an unlabelled one."

### 18. Alerts — the screen an administrator actually leaves open (30s)

`/alerts`:

> "Dr. Rajesh Thakur is rostered but absent — Roster says OPD until 01:28; presence
> says on leave (96% confidence)."

Three kinds: roster-vs-presence mismatch, queue overflow, and patients still pending a
rebooking. Every one names the evidence and the number of patients behind it.

### 19. The network map (20s)

`/map`. Facilities with live status across the HP road network.

> "If the venue has no internet the basemap tiles will not load. The app detects that
> and labels itself **'Basemap offline — positions are real'** — the markers, the
> statuses and every number are ours and still correct."

### 20. The remote control (20s)

`/scenarios`, admin only. The five scenarios from Part 1 as buttons: *Doctor arrives*,
*Walk to surgery*, *Beacon battery dies*, *Calls in sick*, *Roster is wrong*.

> "These post to the same public `/signals` endpoint the simulators and real hardware
> use. A demo button that wrote to the database would make the whole demo a lie."

("surge" is not built — five scenarios shipped. Say so if someone asks for a sixth.)

## Part 5 — Golden Hour and referral (M8, M5)

The last two beats of the scripted scenario in `docs/PRD.md §Demo requirements`.

### 21. "Accident on NH-5 near Rampur" — *PRD M8 accept* (60s)

`/golden-hour`. The incident starts on Rampur; click anywhere on the map to move it.
Choose **General Surgery** and **O−**, then **Rank facilities**.

> "Three facilities, ranked in about forty milliseconds against a three-second budget.
> And every one of them tells you why it is where it is."

Read one card aloud — the reasoning is the deliverable, not the order:

> "IGMC: a hundred and twenty-seven kilometres by road, ten free beds, five units of
> O-negative. And this line — *on the roster but presence unknown, not confirmed at the
> bedside*. We are not claiming the surgeon is there. We are claiming we cannot see him,
> which is a different sentence, and the ranking scores it in the middle rather than
> pretending either way."

Now switch the specialty to **Neurosurgery** and rank again. All three go grey:

> "Ruled out — *no Neurosurgery department here*. Not hidden, not dropped off the
> bottom. A ranking that silently omits a hospital cannot be questioned, so the ones it
> rejects stay on the screen with the reason."

Two labels to point at before anyone asks:
- **"Decision support — not 108 dispatch."** Nothing here moves a vehicle.
- **"Drive time estimated — no OSRM."** See §22.

### 22. "Are those real drive times?" (30s)

Say no first.

> "No. There is no OSRM container running, so those are estimates — straight-line
> distance times a winding factor of 2.2, at thirty-eight kilometres an hour. The factor
> is measured against three real Himachal road pairs, and it puts Rampur to Shimla at a
> hundred and twenty-seven kilometres where the road is about a hundred and thirty. The
> adapter for real OSRM is written and one environment variable switches it on. Until
> someone does that, the screen says the number is estimated — on every single card."

`GET /api/v1/health` reports `"osrm": true` alongside the messaging adapters, so this
is checkable rather than a claim.

### 23. Referral with a bed reservation — *PRD M5 accept* (60s)

`/referrals`.

> "Mandi wants to send a trauma case to Shimla. Placing the referral holds an actual
> ICU bed at the destination — not a note in a WhatsApp group, a row that moves that bed
> out of Shimla's free count the moment it is taken."

Open `/beds` in a second tab and show the destination's free count drop by one, then
come back. Point at the countdown on the row:

> "Two hours, ticking. This is the part that matters. A reservation that only releases
> when somebody remembers to cancel it is how a district hospital comes to believe there
> is an ICU bed in Shimla that was given away three hours ago. So the hold expires on a
> timer, on the server, whether or not anyone has this screen open — and when it does,
> the bed and the specialist's slot are released together."

If someone asks what happens on a race: confirming a hold that expired a second ago is
refused, not resurrected. That bed may already belong to someone else.

### 24. "So how much waiting did you actually remove?" — the closing number (60s)

`/impact`. This is the screen to end on, because it answers the problem statement in
its own words.

> "Three hundred and thirty-four patients told their appointment moved. Every one of
> them told *before* the slot they would have travelled to, with a median of three
> hours' notice. That is the waiting we removed — not three minutes off a queue, a
> journey not made."

Then, before anyone asks, turn the chart around on yourself:

> "And here is the part most teams would hide. Against first-come-first-served with
> spare capacity, we do **not** reduce waiting. Twenty-three minutes against twenty-two
> — we are marginally worse on the raw mean. What changes is *who* waits: a referred
> patient waits zero minutes instead of twenty-five. In a busy department, which is
> every real day in Himachal, mean displacement is seventy-two against a hundred and
> forty-eight. The claim is that the right people wait less. Not that everyone does."

That paragraph is on the screen, not just in your head — the API serves
`honest_reading` alongside the numbers so it cannot drift from them.

Point at the fourth tile last:

> "Fifty-eight patients are still owed a seat. We show that next to the headline rather
> than under it."

### 25. Two drills you run before the room, not in it (30s)

```bash
make load-check      # every doctor in the network replanned; worst case reported
make failure-drill   # stops Redis, proves bookings survive, restarts it
```

> "Load: thirty replans across three hospitals, worst case a hundred and sixty-six
> milliseconds against a five-second budget — thirty times inside it. And we kill Redis
> on purpose: the board stops streaming and says so, but the presence data, the clinic
> lists, the beds and the emergency ranking all keep serving, because the clinical data
> is in Postgres and Redis was never in that path."

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
| Beds screen empty | `make seed-facilities`. It is additive — running it twice is a no-op. |
| Blood table empty | `make ingest-blood` (mock by default, writes SYNTHETIC). |
| `/impact` chart missing | `python ml/compare_fcfs.py` to rebuild the artifact. |
| Anything at all, before you present | `make demo-check`. **12/12** or do not start. It no longer needs a re-seed first. |

## What is NOT built yet (say so if asked)

Phase 1 is complete. Bed management, referral reservation and the Golden Hour router
(§21–§23) are built. Still untouched: Bhashini voice booking, outbound TTS reschedule
calls, the kiosk skin, the Prophet footfall forecast, and the ABDM/eSanjeevani/108/
e-Hospital adapter backbone. The **OSRM container is not built** — see §22 — and the
e-RaktKosh adapter exists but **runs in mock mode**, so every blood figure on screen is
generated and labelled SYNTHETIC.

A "surge" scenario (§20) is the remaining gap inside Phase 1. `make dev` (docker compose) is verified and 8/8, but **present from
`dev-local`** — it starts in seconds, and it is what this runbook describes and what was
rehearsed. (There is no live phone line either: IVR runs in mock telephony, which is the
point of `TELEPHONY_MOCK_MODE`.)

# Swasthya-Setu — Product Requirements

Problem statement (SIH 2026, Govt. of Himachal Pradesh): optimize doctor availability and appointment allocation in hospitals through digital technology and AI.

## The problem

In HP's district and regional hospitals, patients travel hours through mountain terrain to discover the doctor is on leave, in surgery, or double-booked. Appointment slots are allocated against paper rosters, not actual presence. Queues are unmanaged; no-shows waste capacity; referrals between hospitals are blind; emergency routing ignores real road conditions.

## The insight

Every scheduling system fails for the same reason: **it optimizes against the roster, not reality.** Swasthya-Setu's core differentiator is a live doctor-presence layer that feeds the optimizer. Availability in = quality of every downstream decision.

## Users

- **Patients** (incl. low-literacy, feature-phone, Hindi-speaking) — book, get told honestly when to come, get rescheduled proactively.
- **Doctors** — passive presence detection (no app-tapping), visibility into their real queue.
- **Hospital admins / CMOs** — command center: live status, bottlenecks, network view.
- **Referring facilities** — reserve a bed/slot at the destination hospital before sending the patient.

## Tiers

- **Tier 1 — flawless.** Presence engine, appointment/queue optimizer, patient access core (PWA + WhatsApp + SMS), command center. This is the demo spine.
- **Tier 2 — working.** IVR + Bhashini voice + outbound TTS + kiosk channels, bed management + referral reservation, blood availability widget, predictive intelligence, Golden Hour Router (demo scope).
- **Tier 3 — slides only.** See CLAUDE.md §NEVER BUILD. No code exists for these.

---

## Module specifications

Each acceptance criterion is phrased as the judge demo it must survive.

### M1. Doctor Presence Engine (Tier 1)

Fuses multiple weak signals into one authoritative per-doctor state:
`PRESENT_IN_DEPT | PRESENT_ELSEWHERE | ON_ROUNDS | IN_SURGERY | ON_LEAVE | OFF_SHIFT | UNKNOWN` with a confidence score.

Signals (all via simulators; hardware optional): BLE beacon sightings, RFID gate taps, voluntary face-kiosk check-in (InsightFace), Wi-Fi geofence association, roster/shift data, manual admin override. Fusion = state machine with per-signal trust weights and time decay; every transition is logged with its evidence.

**Accepts:**
- "Show me a doctor walking from OPD to surgery." → Inject BLE events via simulator; state flips within 10s on the dashboard; evidence trail visible.
- "What if the beacon battery dies?" → Signal decays; state degrades to lower-confidence roster-based state, never silently stays PRESENT.
- "Privacy?" → Face check-in is voluntary/enrolled; BLE tracks a badge, not a person's phone; retention policy stated on slide.
- "Why not just an attendance app?" → Passive multi-signal beats self-reporting; show fusion overriding a stale roster.

**Non-goals:** patient tracking, CCTV analytics, payroll attendance.

### M2. AI Appointment & Queue Engine (Tier 1)

- Slot allocation as CP-SAT constraint problem: doctor availability (live, from M1), room capacity, priority classes (emergency > referred > elderly/disabled > general), patient travel time.
- XGBoost wait-time prediction per queue position; XGBoost no-show probability, trained/benchmarked on the public 110k-appointment dataset; overbooking of high-no-show slots within a safety cap.
- Auto-rescheduling: doctor goes unavailable → affected appointments re-optimized → patients notified (M3) with new slots ranked by their constraints.

**Accepts:**
- "Doctor calls in sick at 9 AM with 40 booked patients. Show me." → One click (or automatic trigger from M1): plan recomputes in <5s, patients redistributed, notification log shows outbound messages.
- "How do you know the wait predictions are any good?" → Show MAE on held-out benchmark data, on a slide and in a `/metrics` endpoint.
- "Why CP-SAT and not first-come-first-served?" → Side-by-side simulation (SimPy) showing wait-time reduction on the same demand.

**Non-goals:** payment, insurance eligibility, doctor leave management workflows.

### M3. Patient Access Channels (Tier 1: PWA, WhatsApp, SMS · Tier 2: IVR, Bhashini voice, outbound TTS, kiosk)

Single booking API consumed by all channels; channels are thin adapters.

- **PWA:** Hindi + English, offline-capable (PouchDB→CouchDB sync), booking + queue position + reschedule.
- **WhatsApp** (Meta Cloud API adapter): guided booking flow, confirmations, reschedule links.
- **SMS** (MSG91 adapter): confirmations, reschedule notices, structured keyword booking.
- **IVR** (Exotel adapter): DTMF booking for feature phones.
- **Bhashini voice** (constrained scope): Hindi speech → intent for the booking flow only.
- **Outbound TTS calls:** proactive reschedule/reminder calls.
- **Kiosk:** simplified PWA skin for hospital lobby.

**Accepts:**
- "Book an appointment as a farmer with a feature phone." → Live IVR or SMS flow in mock telephony mode, end-to-end to a confirmed slot visible on the dashboard.
- "No internet in the valley?" → PWA booked offline queues locally and syncs when connectivity returns; show it with network throttled off.
- Every confirmation shows the same appointment ID across channel, dashboard, and DB.

**Non-goals:** languages beyond Hindi/English (+Bhashini flow), marketing broadcasts.

### M4. Command Center (Tier 1)

Live dashboard: per-hospital doctor presence board, live queues with predicted waits, alerts (doctor absent vs. roster, queue overflow), network map (Leaflet) of all facilities, manual override controls. WebSocket-driven; no refresh button anywhere.

**Accepts:** every M1/M2 demo above is *shown through* this dashboard; a simulated event appears without user interaction in <2s.

### M5. Bed Management + Referral Reservation (Tier 2)

Ward/bed inventory, occupancy states, cleaning turnaround; referral flow where facility A reserves a bed + specialist slot at facility B with expiry and confirmation.

**Accepts:** "Refer a trauma patient from Mandi to Shimla." → Reserve at destination, see it held on destination dashboard, expiry releases it automatically.

### M6. Blood Availability Widget (Tier 2)

Per-hospital blood stock by group, fed from real e-RaktKosh data snapshots via adapter; surfaced in command center and referral flow.

**Accepts:** "Where's this data from?" → Show the ingest job and the real source; synthetic fallback clearly labeled.

### M7. Predictive Intelligence (Tier 2)

Prophet footfall forecasts calibrated on real HMIS data (seasonality: pilgrimage, festivals, winter). Feeds staffing suggestions and the optimizer's demand expectations.

**Accepts:** backtest chart — forecast vs. actual on held-out HMIS months, error stated honestly.

### M8. Golden Hour Router (Tier 2, demo scope)

OSRM on real HP road network: given an emergency location, rank reachable facilities by drive time × capability (bed from M5, blood from M6, specialist presence from M1).

**Accepts:** "Accident on NH-5 near Rampur." → Ranked facilities with routes on map in <3s, reasoning shown ("skipped X: no neurosurgeon present"). Framed honestly as decision support, not live 108 dispatch (that's Tier 3).

### M9. Integration Backbone (Tier 2, adapter + sandbox scope)

Adapter layer with mock implementations for ABDM (sandbox only), eSanjeevani, 108, e-Hospital. Demonstrates the interface contracts; production integration is Tier 3.

**Accepts:** "How would this plug into ABDM?" → Show the adapter interface, the sandbox call, and the mock flag — honest about current depth.

---

## Data

| Dataset | Use | Fallback |
|---|---|---|
| e-RaktKosh blood stock | M6 | Synthetic, same schema, labeled |
| HMIS footfall | M7 training/backtest | Synthetic seasonal generator |
| 110k-appointment public benchmark | M2 no-show model | (public, always available) |
| HP road network (OSM extract) | M8 routing | Cached extract committed to repo |

## Demo requirements (non-negotiable)

`make demo` on a clean machine, no internet, no hardware: seeds 3 hospitals, ~30 doctors, ~200 patients, a full simulated day, and supports the scripted scenario: morning normal ops → doctor absence → auto-reschedule cascade → emergency Golden Hour routing → referral with bed reservation. Presenter click-path documented in `infra/demo-script.md` (write it in Phase 3).

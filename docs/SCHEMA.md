# Data Model

PostgreSQL 16. All tables: `id UUID PK default gen_random_uuid()`, `created_at`, `updated_at`. Enums are real PG enums (Alembic: define manually, autogenerate misses them). Update this file in the same commit as any migration.

**Delete rules.** A nullable FK means the relationship is optional, so it is `ON DELETE SET NULL` — deleting a bed must not delete the referral that reserved it, and deleting an appointment must not erase its `notifications` row (that table is the demo outbox and judge-facing evidence). A required FK means the row is owned by its parent and is `ON DELETE CASCADE`. The one exception is `appointments.slot_id`, which is `RESTRICT`: a replan must move appointments, never delete slots out from under them. `backend/tests/test_schema.py` pins all three behaviours.

## Core registry

**hospitals** — name, code, district, lat, lng, level(enum: PHC|CHC|DISTRICT|REGIONAL|MEDICAL_COLLEGE), contact
**departments** — hospital_id FK, name, specialty_code, room_count
**users** — name, phone (unique), email?, password_hash?, role(enum: ADMIN|DOCTOR|STAFF|PATIENT), hospital_id FK?
**doctors** — user_id FK, hospital_id FK, department_id FK, specialty, badge_id (unique; what BLE/RFID track), face_enrolled bool, face_embedding jsonb? (voluntary enrolment; the vector only, never an image), avg_consult_minutes
**patients** — user_id FK?, name, phone, registered_via? (channel enum, nullable — set only when the patient signed themselves up through a channel; NULL means a hospital record, and no screen should confuse the two), telegram_chat_id? (nullable; Telegram hands it to us when the patient shares their contact — a bot cannot address anyone by phone number), email? (nullable, not unique — an inbox is the exception here and a family may share one; `ix_patients_email_lower` for the case-insensitive lookup email OTP does), age, gender, village/district, priority_flags jsonb (elderly, disabled, pregnant…), preferred_language(enum: HI|EN)

## Presence (M1)

**shifts** — doctor_id FK, department_id FK, starts_at, ends_at, kind(enum: OPD|WARD|SURGERY|ON_CALL|LEAVE)
**presence_signals** — doctor_id FK (via badge lookup), source(enum: BLE|RFID|FACE|WIFI|ROSTER|MANUAL), zone_id FK?, raw jsonb, observed_at, trust numeric  · *index (doctor_id, observed_at desc); partition/prune >30 days*
**zones** — hospital_id FK, department_id FK?, code (unique per hospital; what a beacon/reader is provisioned with — signals address zones by code, `name` is display-only), name, kind(enum: OPD|WARD|OT|GATE|LOBBY)
**doctor_status** — doctor_id FK (unique), state(enum: PRESENT_IN_DEPT|PRESENT_ELSEWHERE|ON_ROUNDS|IN_SURGERY|ON_LEAVE|OFF_SHIFT|UNKNOWN), confidence numeric, zone_id FK?, since, evidence jsonb (signal ids + scores) — current fused state, one row per doctor
**presence_transitions** — doctor_id FK, from_state, to_state, confidence, evidence jsonb, at — the audit/judge trail

## Scheduling (M2)

**slots** — doctor_id FK, department_id FK, starts_at, ends_at, capacity smallint (>1 = overbook allowance), status(enum: OPEN|FULL|BLOCKED)
**appointments** — patient_id FK, slot_id FK, hospital_id FK, department_id FK, channel(enum: PWA|WHATSAPP|SMS|IVR|VOICE|KIOSK|STAFF|EMAIL|TELEGRAM), priority_class(enum: EMERGENCY|REFERRED|PRIORITY|GENERAL), status(enum: BOOKED|CHECKED_IN|IN_CONSULT|COMPLETED|NO_SHOW|CANCELLED|RESCHEDULED|RESCHEDULE_PENDING — a replan could not seat them; still owed an appointment), token_number, noshow_prob numeric?, predicted_wait_min int?, rescheduled_from FK(appointments)?  · *index (slot_id), (patient_id, status)*
**queue_entries** — appointment_id FK (unique), department_id FK, position int, checked_in_at, called_at?, state(enum: WAITING|CALLED|SERVING|DONE|SKIPPED)
**plan_runs** — trigger(enum: PRESENCE_CHANGE|MANUAL|PERIODIC), scope jsonb, solver_status, objective numeric, duration_ms, moved_count — every CP-SAT run, for the "<5s" claim
**notifications** — appointment_id FK?, patient_id FK, channel, template, payload jsonb, mock bool, status(enum: QUEUED|SENT|DELIVERED|FAILED), sent_at — the demo "outbox"

## Beds & referrals (M5)

**beds** — hospital_id FK, ward, code, kind(enum: GENERAL|ICU|HDU|MATERNITY|ISOLATION), state(enum: FREE|OCCUPIED|RESERVED|CLEANING|OOO)
**bed_allocations** — bed_id FK, patient_id FK?, referral_id FK?, from_at, to_at?
**referrals** — from_hospital_id FK, to_hospital_id FK, patient_id FK, specialty, urgency(enum: ROUTINE|URGENT|EMERGENCY), status(enum: REQUESTED|RESERVED|CONFIRMED|ARRIVED|EXPIRED|CANCELLED), reserved_bed_id FK?, reserved_slot_id FK?, expires_at, notes

## Blood, forecast, routing (M6–M8)

**blood_stock** — hospital_id FK, group(enum: 8 groups), component(enum: WHOLE|PRBC|FFP|PLATELET), units int, as_of, source(enum: ERAKTKOSH|SYNTHETIC)
**footfall_history** — hospital_id FK, department_id FK?, date, visits int, source(enum: HMIS|SYNTHETIC)
**footfall_forecasts** — hospital_id FK, department_id FK?, date, yhat, yhat_lower, yhat_upper, model_version
**emergency_requests** — lat, lng, description, specialty_needed?, created_by FK(users), status
**route_rankings** — emergency_request_id FK, hospital_id FK, rank, drive_minutes, capability_score, reasons jsonb — persisted so the judge demo is replayable

## Relationships (crib)

hospital 1—n department 1—n doctors/slots/zones · doctor 1—1 doctor_status, 1—n shifts/signals/transitions · patient 1—n appointments 1—0..1 queue_entry · referral n—1 both hospitals, 0..1 bed + slot reservations.

## Redis keys

```
presence:{doctor_id}            hash mirror of doctor_status (hot read)   TTL none
queue:{department_id}           list of appointment ids (live order)
ws:dash:{hospital_id}           pub/sub relay channels
lock:replan:{doctor_id}         SET NX EX 30 — dedupe replan triggers
chat:whatsapp:{phone10}         guided booking conversation state         TTL 30 min
otp:code:{phone10}              login code + patient id + attempt count   TTL 5 min
otp:rate:{phone10}              OTP requests in the window                TTL 15 min
cache:slots:{dept}:{date}       json, TTL 60s, busted on replan
```

## PWA offline storage (browser, not a server)

No CouchDB. The offline outbox lives in the browser's `localStorage` under `setu.outbox`
and replays over the normal REST API when connectivity returns (ARCHITECTURE D23).

`setu.outbox`: pending booking intents `{intent_id, patient_id, slot_id, channel, created_at, label}`.
On replay a 409 or 404 drops the intent and the patient is asked to pick again — a slot
taken while they were offline is never silently double-booked.
`setu.token`, `setu.lang`: session token and language choice.

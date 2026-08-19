# Data Model

PostgreSQL 16. All tables: `id UUID PK default gen_random_uuid()`, `created_at`, `updated_at`. Enums are real PG enums (Alembic: define manually, autogenerate misses them). Update this file in the same commit as any migration.

## Core registry

**hospitals** — name, code, district, lat, lng, level(enum: PHC|CHC|DISTRICT|REGIONAL|MEDICAL_COLLEGE), contact
**departments** — hospital_id FK, name, specialty_code, room_count
**users** — name, phone (unique), email?, password_hash?, role(enum: ADMIN|DOCTOR|STAFF|PATIENT), hospital_id FK?
**doctors** — user_id FK, hospital_id FK, department_id FK, specialty, badge_id (unique; what BLE/RFID track), face_enrolled bool, avg_consult_minutes
**patients** — user_id FK?, name, phone, age, gender, village/district, priority_flags jsonb (elderly, disabled, pregnant…), preferred_language(enum: HI|EN)

## Presence (M1)

**shifts** — doctor_id FK, department_id FK, starts_at, ends_at, kind(enum: OPD|WARD|SURGERY|ON_CALL|LEAVE)
**presence_signals** — doctor_id FK (via badge lookup), source(enum: BLE|RFID|FACE|WIFI|ROSTER|MANUAL), zone_id FK?, raw jsonb, observed_at, trust numeric  · *index (doctor_id, observed_at desc); partition/prune >30 days*
**zones** — hospital_id FK, department_id FK?, name, kind(enum: OPD|WARD|OT|GATE|LOBBY) — what beacons/readers map to
**doctor_status** — doctor_id FK (unique), state(enum: PRESENT_IN_DEPT|PRESENT_ELSEWHERE|ON_ROUNDS|IN_SURGERY|ON_LEAVE|OFF_SHIFT|UNKNOWN), confidence numeric, zone_id FK?, since, evidence jsonb (signal ids + scores) — current fused state, one row per doctor
**presence_transitions** — doctor_id FK, from_state, to_state, confidence, evidence jsonb, at — the audit/judge trail

## Scheduling (M2)

**slots** — doctor_id FK, department_id FK, starts_at, ends_at, capacity smallint (>1 = overbook allowance), status(enum: OPEN|FULL|BLOCKED)
**appointments** — patient_id FK, slot_id FK, hospital_id FK, department_id FK, channel(enum: PWA|WHATSAPP|SMS|IVR|VOICE|KIOSK|STAFF), priority_class(enum: EMERGENCY|REFERRED|PRIORITY|GENERAL), status(enum: BOOKED|CHECKED_IN|IN_CONSULT|COMPLETED|NO_SHOW|CANCELLED|RESCHEDULED), token_number, noshow_prob numeric?, predicted_wait_min int?, rescheduled_from FK(appointments)?  · *index (slot_id), (patient_id, status)*
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
cache:slots:{dept}:{date}       json, TTL 60s, busted on replan
```

## CouchDB (PWA offline only)

`outbox_{user}`: pending booking intents `{intent_id, patient, dept, preferred_windows, created_at}` — backend worker consumes, confirms or counter-proposes.
`readcache_{user}`: my appointments + hospital directory snapshots with `synced_at`.

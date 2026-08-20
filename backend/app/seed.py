"""Deterministic seed: 3 HP hospitals, departments, 30 doctors + rosters, 200 patients, admin.

Idempotent — re-running truncates the seeded tables first, so `make seed` is always safe.
Run: cd backend && .venv/bin/python -m app.seed
"""

import asyncio
import math
import random
from datetime import UTC, datetime, time, timedelta

from sqlalchemy import select, text

from app.config import get_settings
from app.db import SessionLocal
from app.models import (
    Appointment,
    AppointmentStatus,
    Channel,
    Department,
    Doctor,
    DoctorStatus,
    Hospital,
    HospitalLevel,
    Language,
    Patient,
    PresenceState,
    PriorityClass,
    Shift,
    ShiftKind,
    Slot,
    SlotStatus,
    User,
    UserRole,
    Zone,
    ZoneKind,
)
from app.security import hash_password

ADMIN_PHONE = "9418000001"
ADMIN_PASSWORD = "setu-admin"  # dev-only; real deployments set it via env before first boot

HOSPITALS = [
    (
        "Indira Gandhi Medical College",
        "IGMC-SML",
        "Shimla",
        31.1048,
        77.1734,
        HospitalLevel.MEDICAL_COLLEGE,
    ),
    ("Zonal Hospital Mandi", "ZH-MND", "Mandi", 31.7080, 76.9318, HospitalLevel.REGIONAL),
    ("District Hospital Kullu", "DH-KLU", "Kullu", 31.9576, 77.1092, HospitalLevel.DISTRICT),
]

# (name, specialty_code, rooms, doctors per hospital)
DEPARTMENTS = [
    ("General Medicine", "GEN_MED", 4, 3),
    ("Orthopaedics", "ORTHO", 2, 2),
    ("Paediatrics", "PAED", 2, 2),
    ("Obstetrics & Gynaecology", "OBGY", 2, 2),
    ("General Surgery", "SURG", 3, 1),
]

FIRST = [
    "Anil",
    "Priya",
    "Rakesh",
    "Sunita",
    "Vikram",
    "Meena",
    "Sanjay",
    "Kavita",
    "Rajesh",
    "Neha",
    "Suresh",
    "Anjali",
    "Deepak",
    "Pooja",
    "Mohan",
]
LAST = ["Sharma", "Thakur", "Verma", "Chauhan", "Negi", "Kapoor", "Rana", "Bhardwaj"]
VILLAGES = [
    "Rampur",
    "Theog",
    "Rohru",
    "Karsog",
    "Sarkaghat",
    "Banjar",
    "Nirmand",
    "Jubbal",
    "Chopal",
    "Sundernagar",
    "Manali",
    "Bhuntar",
]


def unit_vector(rng: random.Random, dim: int = 512) -> list[float]:
    """Stand-in for an ArcFace embedding. Real enrolment runs InsightFace on the
    kiosk image and stores only this vector — the simulator posts one directly."""
    v = [rng.gauss(0, 1) for _ in range(dim)]
    norm = math.sqrt(sum(x * x for x in v))
    return [round(x / norm, 6) for x in v]


# The doctor the "calls in sick at 9 AM with 40 booked patients" demo hangs off.
DEMO_BADGE = "HP-DOC-1001"
DEMO_BOOKINGS = 40


async def seed_clinic_day(db, rng: random.Random, now: datetime, patients: list) -> tuple[int, int]:
    """Slots for every OPD shift, then a plausible booking load on top.

    Two things matter for the M2 demo and both are easy to get wrong:
    the demo doctor must have ~40 appointments still *ahead* of now, and the rest of
    the department must keep real gaps, or a replan has nowhere to move anyone.
    """
    doctors = (await db.execute(select(Doctor))).scalars().all()
    shifts = (await db.execute(select(Shift).where(Shift.kind == ShiftKind.OPD))).scalars().all()
    by_doctor: dict = {}
    for shift in shifts:
        by_doctor.setdefault(shift.doctor_id, []).append(shift)

    horizon = now + timedelta(days=2)
    all_slots: list[Slot] = []
    slots_by_doctor: dict = {}
    for doctor in doctors:
        for shift in sorted(by_doctor.get(doctor.id, []), key=lambda s: s.starts_at):
            if shift.starts_at > horizon:
                continue
            cursor = shift.starts_at
            length = timedelta(minutes=doctor.avg_consult_minutes)
            while cursor + length <= shift.ends_at:
                slot = Slot(
                    doctor_id=doctor.id,
                    department_id=doctor.department_id,
                    starts_at=cursor,
                    ends_at=cursor + length,
                    capacity=1,
                    status=SlotStatus.OPEN,
                )
                all_slots.append(slot)
                slots_by_doctor.setdefault(doctor.id, []).append(slot)
                cursor += length
    db.add_all(all_slots)
    await db.flush()

    demo_doctor = next(d for d in doctors if d.badge_id == DEMO_BADGE)
    booked = 0
    for doctor in doctors:
        upcoming = [
            s
            for s in slots_by_doctor.get(doctor.id, [])
            if now <= s.starts_at < now + timedelta(hours=12)
        ]
        past = [s for s in slots_by_doctor.get(doctor.id, []) if s.starts_at < now]

        if doctor.id == demo_doctor.id:
            # the clinic list the "calls in sick" scenario has to redistribute
            chosen = upcoming[:DEMO_BOOKINGS]
        else:
            # a real clinic is not booked front to back; sample so gaps stay scattered
            chosen = rng.sample(upcoming, k=int(len(upcoming) * 0.45)) if upcoming else []
        chosen += rng.sample(past, k=int(len(past) * 0.8)) if past else []

        for slot in chosen:
            patient = rng.choice(patients)
            flags = patient.priority_flags
            priority = (
                PriorityClass.PRIORITY
                if (flags.get("elderly") or flags.get("disabled") or flags.get("pregnant"))
                else PriorityClass.GENERAL
            )
            db.add(
                Appointment(
                    patient_id=patient.id,
                    slot_id=slot.id,
                    hospital_id=doctor.hospital_id,
                    department_id=doctor.department_id,
                    channel=rng.choice([Channel.PWA, Channel.WHATSAPP, Channel.SMS, Channel.STAFF]),
                    priority_class=priority,
                    status=(
                        AppointmentStatus.COMPLETED
                        if slot.starts_at < now
                        else AppointmentStatus.BOOKED
                    ),
                    token_number=booked % 200 + 1,
                )
            )
            slot.status = SlotStatus.FULL
            booked += 1
    await db.flush()
    await _score_noshow(db, now)
    return len(all_slots), booked


async def _score_noshow(db, now: datetime) -> None:
    """Give every upcoming appointment a no-show probability from the committed model.

    Without this the queue view shows a dash for most patients, which reads as broken
    rather than as "not scored yet".
    """
    from app.services import models as ml

    if not ml.available():
        print("        (no-show model unavailable — probabilities left unset)")
        return

    rows = (
        await db.execute(
            select(Appointment, Slot, Patient)
            .join(Slot, Slot.id == Appointment.slot_id)
            .join(Patient, Patient.id == Appointment.patient_id)
            .where(Appointment.status == AppointmentStatus.BOOKED, Slot.starts_at >= now)
        )
    ).all()
    for appt, slot, patient in rows:
        flags = patient.priority_flags or {}
        appt.noshow_prob = ml.predict_noshow(
            # booked "yesterday": the seed has no real booking timestamps, and lead
            # time is the model's strongest feature so it must not be zero for everyone
            booked_at=now - timedelta(days=1),
            appointment_at=slot.starts_at,
            age=patient.age,
            is_female=(patient.gender or "F").upper().startswith("F"),
            handicap=bool(flags.get("disabled")),
        )
    await db.flush()
    await _seed_long_lead_bookings(db, now)


# A clinic with no likely no-shows never exercises overbooking, so the demo would ship
# a feature nobody has ever seen run. These are not faked probabilities — they are the
# risk profile the real 110k dataset actually flags: booked months ahead, no reminder
# received, young patient. The model scores them ~0.55 on its own.
LONG_LEAD_DAYS = 95
LONG_LEAD_COUNT = 3


async def _seed_long_lead_bookings(db, now: datetime) -> None:
    """Give a few of the demo doctor's colleagues a genuinely high-risk booking."""
    from app.services import models as ml

    demo = (await db.execute(select(Doctor).where(Doctor.badge_id == DEMO_BADGE))).scalar_one()
    rows = (
        await db.execute(
            select(Appointment, Slot, Patient)
            .join(Slot, Slot.id == Appointment.slot_id)
            .join(Patient, Patient.id == Appointment.patient_id)
            .where(
                Appointment.status == AppointmentStatus.BOOKED,
                Appointment.department_id == demo.department_id,
                Slot.doctor_id != demo.id,  # must be a colleague, or it is not overbookable
                Slot.starts_at >= now,
            )
            .order_by(Slot.starts_at)
            .limit(LONG_LEAD_COUNT)
        )
    ).all()

    booked_at = now - timedelta(days=LONG_LEAD_DAYS)
    for appt, slot, patient in rows:
        patient.age = 21  # the demographic the dataset flags hardest
        appt.created_at = booked_at  # so the lead time is inspectable, not just asserted
        appt.noshow_prob = ml.predict_noshow(
            booked_at=booked_at,
            appointment_at=slot.starts_at,
            age=patient.age,
            is_female=True,
            sms_received=False,  # never got a reminder
        )
    await db.flush()
    if rows:
        print(
            f"        {len(rows)} long-lead bookings "
            f"(~{LONG_LEAD_DAYS}d ahead, no reminder) -> "
            f"no-show {min(float(a.noshow_prob) for a, _, _ in rows):.2f}"
            f"-{max(float(a.noshow_prob) for a, _, _ in rows):.2f}, overbookable"
        )


async def main() -> None:
    rng = random.Random(2026)  # fixed: the demo must look the same every run
    now = datetime.now(UTC)
    today = now.date()

    async with SessionLocal() as db:
        await db.execute(
            text(
                "TRUNCATE hospitals, departments, users, doctors, patients, shifts, zones, "
                "doctor_status, slots, appointments, queue_entries, notifications, plan_runs "
                "RESTART IDENTITY CASCADE"
            )
        )

        hospitals = [
            Hospital(
                name=n,
                code=c,
                district=d,
                lat=lat,
                lng=lng,
                level=lv,
                contact=f"0177-2{rng.randint(100000, 999999)}",
            )
            for n, c, d, lat, lng, lv in HOSPITALS
        ]
        db.add_all(hospitals)
        await db.flush()

        db.add(
            User(
                name="Demo Administrator",
                phone=ADMIN_PHONE,
                email="admin@swasthya-setu.hp.gov.in",
                password_hash=hash_password(ADMIN_PASSWORD),
                role=UserRole.ADMIN,
                hospital_id=hospitals[0].id,
            )
        )

        badge = 1000
        doctor_count = 0
        for hosp in hospitals:
            # shared zones every doctor can move through — personas need somewhere
            # to walk to that is not their own OPD room
            for kind, label in [
                (ZoneKind.GATE, "Main Gate"),
                (ZoneKind.LOBBY, "Reception Lobby"),
                (ZoneKind.WARD, "General Ward"),
                (ZoneKind.OT, "Operation Theatre"),
            ]:
                db.add(
                    Zone(
                        hospital_id=hosp.id,
                        department_id=None,
                        code=f"{hosp.code}-{kind.value}",
                        name=label,
                        kind=kind,
                    )
                )

            for dept_name, code, rooms, per_hosp in DEPARTMENTS:
                dept = Department(
                    hospital_id=hosp.id, name=dept_name, specialty_code=code, room_count=rooms
                )
                db.add(dept)
                await db.flush()

                db.add(
                    Zone(
                        hospital_id=hosp.id,
                        department_id=dept.id,
                        code=f"{hosp.code}-{code}-OPD",
                        name=f"{dept_name} OPD",
                        kind=ZoneKind.OPD,
                    )
                )

                for _ in range(per_hosp):
                    badge += 1
                    doctor_count += 1
                    user = User(
                        name=f"Dr. {rng.choice(FIRST)} {rng.choice(LAST)}",
                        phone=f"94180{badge:05d}",
                        email=None,
                        password_hash=hash_password("doctor"),
                        role=UserRole.DOCTOR,
                        hospital_id=hosp.id,
                    )
                    db.add(user)
                    await db.flush()

                    enrolled = rng.random() < 0.6
                    badge_id = f"HP-DOC-{badge}"
                    doc = Doctor(
                        user_id=user.id,
                        hospital_id=hosp.id,
                        department_id=dept.id,
                        specialty=code,
                        badge_id=badge_id,
                        face_enrolled=enrolled,
                        face_embedding=unit_vector(rng) if enrolled else None,
                        # the demo doctor is pinned to 10 min so a 7-hour day-0 clinic
                        # holds the 40 appointments PRD §M2's accept scenario names
                        avg_consult_minutes=(
                            10 if badge_id == DEMO_BADGE else rng.choice([8, 10, 12, 15])
                        ),
                    )
                    db.add(doc)
                    await db.flush()

                    # A week of OPD rosters, so presence has something to fall back to.
                    # Day 0 is anchored around *now* rather than a fixed clock hour:
                    # `make seed` must leave doctors mid-shift whatever time the demo
                    # is rehearsed at, or every board reads OFF_SHIFT (Iron Rule 4).
                    for day in range(7):
                        if day == 0:
                            # long enough that ~40 slots are still ahead of "now"
                            # whatever hour the demo is rehearsed at
                            start = now - timedelta(hours=1)
                        else:
                            start = datetime.combine(
                                today + timedelta(days=day), time(9, 0), tzinfo=UTC
                            )
                        db.add(
                            Shift(
                                doctor_id=doc.id,
                                department_id=dept.id,
                                starts_at=start,
                                ends_at=start + timedelta(hours=8 if day == 0 else 6),
                                kind=ShiftKind.OPD,
                            )
                        )

                    # every doctor starts UNKNOWN — presence is earned from signals, not assumed
                    db.add(
                        DoctorStatus(
                            doctor_id=doc.id,
                            state=PresenceState.UNKNOWN,
                            confidence=0,
                            since=now,
                            evidence={"reason": "seeded, no signals yet"},
                        )
                    )

        patients = []
        for i in range(200):
            age = rng.randint(1, 88)
            patients.append(
                Patient(
                    name=f"{rng.choice(FIRST)} {rng.choice(LAST)}",
                    phone=f"98{rng.randint(10000000, 99999999)}",
                    age=age,
                    gender=rng.choice(["M", "F"]),
                    village=rng.choice(VILLAGES),
                    district=rng.choice(["Shimla", "Mandi", "Kullu"]),
                    priority_flags={
                        "elderly": age >= 65,
                        "disabled": rng.random() < 0.05,
                        "pregnant": rng.random() < 0.04,
                    },
                    preferred_language=Language.HI if i % 4 else Language.EN,
                )
            )
        # One patient you can actually receive mail as, so email OTP is demoable
        # against a real inbox. Deliberately the first seeded patient — deterministic
        # under the fixed RNG — and nobody else, because inventing 200 addresses would
        # be inventing 200 facts.
        demo_email = get_settings().demo_patient_email.strip()
        if demo_email:
            patients[0].email = demo_email

        db.add_all(patients)
        await db.flush()

        slots, appointments = await seed_clinic_day(db, rng, now, patients)

        await db.commit()
        print(f"seeded {len(hospitals)} hospitals, {doctor_count} doctors, 200 patients")
        print(f"        {slots} slots, {appointments} appointments ({DEMO_BADGE} is the busy one)")
        print(f"admin login: {ADMIN_PHONE} / {ADMIN_PASSWORD}")
        print(f"patient login: {patients[0].phone} (phone OTP)", end="")
        print(
            f" or {demo_email} (email OTP)"
            if demo_email
            else " — set DEMO_PATIENT_EMAIL for email OTP"
        )


if __name__ == "__main__":
    asyncio.run(main())

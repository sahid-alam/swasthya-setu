"""Deterministic seed: 3 HP hospitals, departments, 30 doctors + rosters, 200 patients, admin.

Idempotent — re-running truncates the seeded tables first, so `make seed` is always safe.
Run: cd backend && .venv/bin/python -m app.seed
"""

import asyncio
import math
import random
from datetime import UTC, datetime, time, timedelta

from sqlalchemy import text

from app.db import SessionLocal
from app.models import (
    Department,
    Doctor,
    DoctorStatus,
    Hospital,
    HospitalLevel,
    Language,
    Patient,
    PresenceState,
    Shift,
    ShiftKind,
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


async def main() -> None:
    rng = random.Random(2026)  # fixed: the demo must look the same every run
    now = datetime.now(UTC)
    today = now.date()

    async with SessionLocal() as db:
        await db.execute(
            text(
                "TRUNCATE hospitals, departments, users, doctors, patients, shifts, zones, "
                "doctor_status RESTART IDENTITY CASCADE"
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
                    doc = Doctor(
                        user_id=user.id,
                        hospital_id=hosp.id,
                        department_id=dept.id,
                        specialty=code,
                        badge_id=f"HP-DOC-{badge}",
                        face_enrolled=enrolled,
                        face_embedding=unit_vector(rng) if enrolled else None,
                        avg_consult_minutes=rng.choice([8, 10, 12, 15]),
                    )
                    db.add(doc)
                    await db.flush()

                    # A week of OPD rosters, so presence has something to fall back to.
                    # Day 0 is anchored around *now* rather than a fixed clock hour:
                    # `make seed` must leave doctors mid-shift whatever time the demo
                    # is rehearsed at, or every board reads OFF_SHIFT (Iron Rule 4).
                    for day in range(7):
                        if day == 0:
                            start = now - timedelta(hours=2)
                        else:
                            start = datetime.combine(
                                today + timedelta(days=day), time(9, 0), tzinfo=UTC
                            )
                        db.add(
                            Shift(
                                doctor_id=doc.id,
                                department_id=dept.id,
                                starts_at=start,
                                ends_at=start + timedelta(hours=6),
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

        for i in range(200):
            age = rng.randint(1, 88)
            db.add(
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

        await db.commit()
        print(f"seeded {len(hospitals)} hospitals, {doctor_count} doctors, 200 patients")
        print(f"admin login: {ADMIN_PHONE} / {ADMIN_PASSWORD}")


if __name__ == "__main__":
    asyncio.run(main())

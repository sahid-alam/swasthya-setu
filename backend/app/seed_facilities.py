"""Beds and blood stock for M5 (referral reservation) and M8 (Golden Hour ranking).

Deliberately NOT part of `app.seed`. That one truncates `patients`, which destroys a
live Telegram link and the demo patient's phone and email — so facility inventory, which
has nothing to do with patients, gets its own additive pass:

    make seed-facilities

Idempotent by insert-if-absent on the natural keys (hospital + bed code, hospital +
group + component), so running it twice changes nothing and running it after a real
`make seed` refills what CASCADE removed.

Blood stock is SYNTHETIC and every row says so in its `source` column, which is what the
§9d SYNTHETIC DATA chip reads. M6 — the real e-RaktKosh ingest adapter — is NOT built;
these rows exist because M8's capability ranking needs a blood input, and a number with
no provenance in front of a judge is worse than no number at all.
"""

import asyncio
import random
from datetime import UTC, datetime

from sqlalchemy import select

from app.db import SessionLocal
from app.models import (
    Bed,
    BedKind,
    BedState,
    BloodComponent,
    BloodGroup,
    BloodSource,
    BloodStock,
    Hospital,
    HospitalLevel,
)

# Ward mix by hospital level. A district hospital does not run an eight-bed HDU, and a
# ranking that pretends otherwise would send a trauma case up the wrong valley.
WARDS: dict[HospitalLevel, list[tuple[str, BedKind, int]]] = {
    HospitalLevel.MEDICAL_COLLEGE: [
        ("Emergency", BedKind.GENERAL, 8),
        ("ICU", BedKind.ICU, 12),
        ("HDU", BedKind.HDU, 8),
        ("General Ward", BedKind.GENERAL, 40),
        ("Maternity", BedKind.MATERNITY, 12),
        ("Isolation", BedKind.ISOLATION, 6),
    ],
    HospitalLevel.REGIONAL: [
        ("Emergency", BedKind.GENERAL, 5),
        ("ICU", BedKind.ICU, 6),
        ("General Ward", BedKind.GENERAL, 24),
        ("Maternity", BedKind.MATERNITY, 8),
        ("Isolation", BedKind.ISOLATION, 3),
    ],
    HospitalLevel.DISTRICT: [
        ("Emergency", BedKind.GENERAL, 3),
        ("ICU", BedKind.ICU, 3),
        ("General Ward", BedKind.GENERAL, 16),
        ("Maternity", BedKind.MATERNITY, 5),
    ],
}

# A ward that is 100% free reads as a mock. These are the odds a given bed starts in
# something other than FREE — occupancy, a turnaround, a broken bed.
OCCUPANCY = [(BedState.OCCUPIED, 0.55), (BedState.CLEANING, 0.08), (BedState.OOO, 0.03)]


def _initial_state(rng: random.Random) -> BedState:
    roll = rng.random()
    cumulative = 0.0
    for state, share in OCCUPANCY:
        cumulative += share
        if roll < cumulative:
            return state
    return BedState.FREE


async def main() -> None:
    rng = random.Random(2026)  # fixed: the demo must look the same every run
    now = datetime.now(UTC)
    added_beds = added_stock = 0

    async with SessionLocal() as db:
        hospitals = (await db.execute(select(Hospital))).scalars().all()
        if not hospitals:
            raise SystemExit("no hospitals — run `make seed` first")

        for hospital in hospitals:
            existing = {
                code
                for code in (
                    await db.execute(select(Bed.code).where(Bed.hospital_id == hospital.id))
                )
                .scalars()
                .all()
            }
            for ward, kind, count in WARDS[hospital.level]:
                for n in range(1, count + 1):
                    # Stable and human-readable, and the key this script is idempotent on.
                    code = f"{ward[:3].upper()}-{n:02d}"
                    if code in existing:
                        continue
                    db.add(
                        Bed(
                            hospital_id=hospital.id,
                            ward=ward,
                            code=code,
                            kind=kind,
                            state=_initial_state(rng),
                        )
                    )
                    added_beds += 1

            held = {
                (group, component)
                for group, component in (
                    await db.execute(
                        select(BloodStock.group, BloodStock.component).where(
                            BloodStock.hospital_id == hospital.id
                        )
                    )
                ).all()
            }
            for group in BloodGroup:
                for component in (BloodComponent.PRBC, BloodComponent.WHOLE):
                    if (group, component) in held:
                        continue
                    # Negative groups are genuinely scarce in HP district stores, and
                    # O_NEG scarcity is exactly what makes a Golden Hour ranking
                    # interesting rather than decorative.
                    scarce = group.value.endswith("_NEG")
                    ceiling = 4 if scarce else 18
                    if hospital.level == HospitalLevel.DISTRICT:
                        ceiling = max(1, ceiling // 3)
                    db.add(
                        BloodStock(
                            hospital_id=hospital.id,
                            group=group,
                            component=component,
                            units=rng.randint(0, ceiling),
                            as_of=now,
                            source=BloodSource.SYNTHETIC,
                        )
                    )
                    added_stock += 1

        await db.commit()

    print(f"seed-facilities: +{added_beds} beds, +{added_stock} blood stock rows")
    if not added_beds and not added_stock:
        print("  (nothing to do — already seeded)")


if __name__ == "__main__":
    asyncio.run(main())

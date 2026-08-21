"""Blood stock ingest — PRD §M6.

    make ingest-blood

A job someone runs, not a background timer: a scraper hitting a public health portal
on a loop is not a thing to leave running unattended, and the demo does not need fresh
stock every minute.

Whichever adapter the factory hands back, each reading carries its own `source`, so a
generated number can never be written to the same column as a government one. The row
is upserted on (hospital, group, component) — a facility has one current holding of
O-negative PRBC, not a history of them.

A live run that returns nothing (portal down, no internet) is a **no-op**, not a wipe.
Overwriting real stock with zeroes because a government website timed out would be
worse than showing yesterday's number with yesterday's timestamp on it.
"""

import asyncio

from sqlalchemy import select

from app.adapters.factory import blood as blood_adapter
from app.db import SessionLocal
from app.models import BloodStock, Hospital, HospitalLevel

# A district hospital does not hold what a medical college holds.
SCALE = {
    HospitalLevel.MEDICAL_COLLEGE: 1.0,
    HospitalLevel.REGIONAL: 0.6,
    HospitalLevel.DISTRICT: 0.3,
}


async def main() -> None:
    adapter = blood_adapter()
    written = skipped = 0

    async with SessionLocal() as db:
        hospitals = (await db.execute(select(Hospital))).scalars().all()
        if not hospitals:
            raise SystemExit("no hospitals — run `make seed` first")

        for hospital in hospitals:
            readings = await adapter.stock_for(
                hospital_code=hospital.code, scale=SCALE.get(hospital.level, 1.0)
            )
            if not readings:
                # Live adapter got nothing. Keep what is stored rather than zeroing it.
                skipped += 1
                print(f"  {hospital.name}: no readings — existing stock kept")
                continue

            held = {
                (s.group, s.component): s
                for s in (
                    await db.execute(
                        select(BloodStock).where(BloodStock.hospital_id == hospital.id)
                    )
                )
                .scalars()
                .all()
            }
            for reading in readings:
                row = held.get((reading.group, reading.component))
                if row is None:
                    db.add(
                        BloodStock(
                            hospital_id=hospital.id,
                            group=reading.group,
                            component=reading.component,
                            units=reading.units,
                            as_of=reading.as_of,
                            source=reading.source,
                        )
                    )
                else:
                    row.units = reading.units
                    row.as_of = reading.as_of
                    row.source = reading.source
                written += 1
            print(f"  {hospital.name}: {len(readings)} readings ({readings[0].source.value})")

        await db.commit()

    print(f"ingest-blood: {written} holdings written, {skipped} facility(ies) left untouched")


if __name__ == "__main__":
    asyncio.run(main())

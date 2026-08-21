"""Load sanity — PRD §M2 accept: "a hospital-day replan under 5s".

    make load-check

The claim on stage is "<5 seconds". `demo-check` proves it once, for one doctor. This
proves it for **every doctor in the network**, and reports the worst case rather than
the average, because the worst case is the one that happens in front of a judge.

It runs each replan with `apply=False`, so the solver does the full job and nothing is
written: no appointment moves, no notification is sent, no doctor is left on leave. A
load test that mutated the demo data would be a load test you could only run once.
"""

import asyncio
import os
import statistics
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from sqlalchemy import func, select  # noqa: E402

from app.db import SessionLocal  # noqa: E402
from app.models import (
    Appointment,
    AppointmentStatus,
    Doctor,
    Hospital,
    Slot,
)  # noqa: E402
from app.services import scheduling  # noqa: E402

BUDGET_MS = 5000


async def main() -> None:
    async with SessionLocal() as db:
        hospitals = len((await db.execute(select(Hospital))).scalars().all())
        doctors = (await db.execute(select(Doctor))).scalars().all()
        if not doctors:
            raise SystemExit("no doctors — run `make seed` first")

        print(f"replanning every doctor across {hospitals} hospitals ({len(doctors)} doctors)")
        print("dry run: apply=False, so nothing is written\n")

        timings, worst, worst_name, total_moved = [], 0.0, "", 0
        for doctor in doctors:
            booked = (
                await db.execute(
                    select(func.count(Appointment.id))
                    .join(Slot, Slot.id == Appointment.slot_id)
                    .where(
                        Slot.doctor_id == doctor.id,
                        Slot.starts_at >= func.now(),
                        Appointment.status == AppointmentStatus.BOOKED,
                    )
                )
            ).scalar_one()

            started = time.perf_counter()
            result = await scheduling.replan_doctor(db, doctor, apply=False, publish=False)
            elapsed = (time.perf_counter() - started) * 1000
            timings.append(elapsed)
            total_moved += result.moved_count
            if elapsed > worst:
                worst, worst_name = elapsed, doctor.badge_id
            if booked:
                print(
                    f"  {doctor.badge_id}: {booked:>3} booked  "
                    f"{result.status:<14} {elapsed:>7.1f} ms  moved={result.moved_count}"
                )

        # Nothing was applied, but a dry run still opened a transaction.
        await db.rollback()

    print(
        f"\n{len(timings)} replans | median {statistics.median(timings):.1f} ms "
        f"| p95 {sorted(timings)[int(len(timings) * 0.95) - 1]:.1f} ms "
        f"| worst {worst:.1f} ms ({worst_name})"
    )
    print(f"total {sum(timings):.0f} ms for the whole network | {total_moved} patients re-seatable")

    if worst > BUDGET_MS:
        print(f"\nFAIL: worst case {worst:.1f} ms exceeds the {BUDGET_MS} ms budget")
        sys.exit(1)
    print(f"PASS: worst case is {BUDGET_MS / worst:.0f}x inside the {BUDGET_MS} ms budget")


if __name__ == "__main__":
    asyncio.run(main())

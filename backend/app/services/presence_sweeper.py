"""Re-fuses presence on a timer so absence of signal is itself information.

PRD §M1: "What if the beacon battery dies?" — the answer is only true if something
recomputes while nothing is arriving.
"""

import asyncio
import logging
from datetime import UTC, datetime

from sqlalchemy import select

from app.db import SessionLocal
from app.models import Doctor
from app.services.presence import recompute

log = logging.getLogger("swasthya.presence")


async def sweep_once() -> int:
    """Returns how many doctors changed state."""
    changed = 0
    async with SessionLocal() as db:
        doctors = (await db.execute(select(Doctor))).scalars().all()
        now = datetime.now(UTC)
        for doctor in doctors:
            _, flipped = await recompute(db, doctor, now)
            changed += int(flipped)
        await db.commit()
    if changed:
        log.info("presence sweep changed %d doctors", changed)
    return changed


async def sweep_forever(interval_seconds: int) -> None:
    # ponytail: full table scan every tick. Fine for 3 hospitals; if this ever covers
    # a state, filter to doctors whose newest signal is older than the shortest tau.
    while True:
        try:
            await asyncio.sleep(interval_seconds)
            await sweep_once()
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("presence sweep failed; continuing")

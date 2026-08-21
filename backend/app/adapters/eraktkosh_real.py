"""e-RaktKosh, the real portal — PRD §M6.

Selected only when `ERAKTKOSH_MOCK_MODE=false`. Set in `.env` (never in code):

    ERAKTKOSH_MOCK_MODE=false
    ERAKTKOSH_BASE_URL=https://www.eraktkosh.mohfw.gov.in

**Read this before switching it on.** e-RaktKosh publishes no documented public JSON
API. This talks to the availability endpoint its own web UI calls, which means:

- the response shape is not a contract and can change without notice,
- it needs the venue's internet, and
- a government portal is entitled to be slow or down on the morning of a demo.

So it fails *soft*: any error at all and the caller keeps whatever stock it already had,
rather than overwriting real numbers with nothing. It is never the default, and
`GET /api/v1/health` reports whether it is live so nobody has to guess whether the
figures on screen came from the government or from us.

Nothing here is scraped on a timer. Ingest is a job someone runs
(`make ingest-blood`), because a scraper hitting a public health portal on a loop is
not a thing to leave running unattended.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

import httpx

from app.adapters.base import BloodAdapter, BloodReading
from app.config import get_settings
from app.models import BloodComponent, BloodGroup, BloodSource

log = logging.getLogger(__name__)

TIMEOUT_SECONDS = 8.0

# The portal's own group labels, mapped onto ours. Anything it sends that is not in
# here is skipped rather than guessed at.
GROUP_FROM_PORTAL = {
    "A+": BloodGroup.A_POS,
    "A-": BloodGroup.A_NEG,
    "B+": BloodGroup.B_POS,
    "B-": BloodGroup.B_NEG,
    "AB+": BloodGroup.AB_POS,
    "AB-": BloodGroup.AB_NEG,
    "O+": BloodGroup.O_POS,
    "O-": BloodGroup.O_NEG,
}

COMPONENT_FROM_PORTAL = {
    "Whole Blood": BloodComponent.WHOLE,
    "Packed Red Blood Cells": BloodComponent.PRBC,
    "Fresh Frozen Plasma": BloodComponent.FFP,
    "Platelet Concentrate": BloodComponent.PLATELET,
}


class ERaktKosh(BloodAdapter):
    async def stock_for(self, *, hospital_code: str, scale: float = 1.0) -> list[BloodReading]:
        settings = get_settings()
        base = (settings.eraktkosh_base_url or "").rstrip("/")
        if not base:
            log.warning("ERAKTKOSH_MOCK_MODE=false but ERAKTKOSH_BASE_URL is unset")
            return []

        url = f"{base}/BLDAHIMS/bloodbank/nearbyBB.cnt"
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
                r = await client.get(url, params={"stateCode": "12", "districtCode": hospital_code})
            r.raise_for_status()
            rows = r.json().get("data", [])
        except Exception as exc:  # noqa: BLE001 — a portal outage is not our outage
            # Soft failure on purpose: returning [] makes the ingest job a no-op, so
            # whatever stock is already stored survives rather than being wiped.
            log.warning("e-RaktKosh unreachable (%s); keeping existing stock", exc)
            return []

        now = datetime.now(UTC)
        readings = []
        for row in rows:
            group = GROUP_FROM_PORTAL.get(str(row.get("bloodGroup", "")).strip())
            component = COMPONENT_FROM_PORTAL.get(str(row.get("component", "")).strip())
            if group is None or component is None:
                continue
            try:
                units = int(row.get("availableUnits", 0))
            except (TypeError, ValueError):
                continue
            readings.append(
                BloodReading(
                    group=group,
                    component=component,
                    units=units,
                    as_of=now,
                    source=BloodSource.ERAKTKOSH,
                )
            )
        return readings

    async def health(self) -> bool:
        settings = get_settings()
        base = (settings.eraktkosh_base_url or "").rstrip("/")
        if not base:
            return False
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                r = await client.get(base)
            return r.status_code < 500
        except Exception:  # noqa: BLE001 — a probe must never raise
            return False

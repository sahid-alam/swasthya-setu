"""OSRM over a real Himachal Pradesh road extract.

Selected only when `OSRM_MOCK_MODE=false`. Set in `.env` (never in code):

    OSRM_MOCK_MODE=false
    OSRM_BASE_URL=http://localhost:5000

Bring one up with an HP extract (needs internet once, to fetch the extract):

    wget https://download.geofabrik.de/asia/india/northern-zone-latest.osm.pbf
    docker run -t -v "$PWD:/data" osrm/osrm-backend osrm-extract -p /opt/car.lua \\
      /data/northern-zone-latest.osm.pbf
    docker run -t -v "$PWD:/data" osrm/osrm-backend osrm-partition /data/northern-zone-latest
    docker run -t -v "$PWD:/data" osrm/osrm-backend osrm-customize /data/northern-zone-latest
    docker run -p 5000:5000 -v "$PWD:/data" osrm/osrm-backend osrm-routed --algorithm mld \\
      /data/northern-zone-latest

One `/table` request answers origin-to-all-hospitals, so the <3s Golden Hour budget does
not spend N round trips. A failure here degrades to the offline estimator rather than
crashing the ranking — an emergency screen that shows nothing is worse than one that
shows a geometric estimate and says so.
"""

from __future__ import annotations

import asyncio
import logging
import uuid

import httpx

from app.adapters.base import Leg, RoutingAdapter
from app.adapters.osrm_mock import MockOsrm
from app.config import get_settings

log = logging.getLogger(__name__)

TIMEOUT_SECONDS = 5.0
ATTEMPTS = 3


class Osrm(RoutingAdapter):
    async def table(
        self, *, origin: tuple[float, float], destinations: list[tuple[uuid.UUID, float, float]]
    ) -> list[Leg]:
        settings = get_settings()
        base = (settings.osrm_base_url or "").rstrip("/")
        if not base:
            log.warning("OSRM_MOCK_MODE=false but OSRM_BASE_URL is unset; using the estimator")
            return await MockOsrm().table(origin=origin, destinations=destinations)

        # OSRM takes lng,lat — the reverse of every other coordinate in this codebase.
        points = [f"{origin[1]},{origin[0]}"] + [f"{lng},{lat}" for _, lat, lng in destinations]
        url = f"{base}/table/v1/driving/{';'.join(points)}"
        params = {
            "sources": "0",
            "destinations": ";".join(str(i + 1) for i in range(len(destinations))),
            "annotations": "duration,distance",
        }

        for attempt in range(1, ATTEMPTS + 1):
            try:
                async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
                    r = await client.get(url, params=params)
                r.raise_for_status()
                body = r.json()
                if body.get("code") != "Ok":
                    raise ValueError(body.get("message", body.get("code")))
                durations = body["durations"][0]
                distances = body.get("distances", [[None] * len(destinations)])[0]
                legs = []
                for i, (hospital_id, _, _) in enumerate(destinations):
                    seconds, metres = durations[i], distances[i]
                    if seconds is None:
                        # Unroutable — off-network, or across a break in the extract.
                        # Fall back for this one leg rather than dropping the hospital.
                        legs.extend(
                            await MockOsrm().table(origin=origin, destinations=[destinations[i]])
                        )
                        continue
                    legs.append(
                        Leg(
                            hospital_id=hospital_id,
                            km=round((metres or 0) / 1000, 1),
                            minutes=round(seconds / 60, 1),
                            mock=False,
                        )
                    )
                return legs
            except Exception as exc:  # noqa: BLE001 — every failure degrades identically
                if attempt == ATTEMPTS:
                    log.warning(
                        "OSRM failed after %s attempts (%s); using the estimator", attempt, exc
                    )
                    return await MockOsrm().table(origin=origin, destinations=destinations)
                await asyncio.sleep(0.2 * 2 ** (attempt - 1))
        return await MockOsrm().table(origin=origin, destinations=destinations)

    async def health(self) -> bool:
        settings = get_settings()
        base = (settings.osrm_base_url or "").rstrip("/")
        if not base:
            return False
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                # Any well-formed route request is a reachability probe; Shimla to itself.
                r = await client.get(f"{base}/table/v1/driving/77.1734,31.1048")
            return r.status_code == 200
        except Exception:  # noqa: BLE001 — a probe must never raise
            return False

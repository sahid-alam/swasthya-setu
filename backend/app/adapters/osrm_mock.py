"""Offline drive-time estimates for the Golden Hour router (M8).

The default, per Iron Rule 4: `make demo` runs on a clean machine with no internet and
no OSRM container, and the Golden Hour ranking still has to come out.

Great-circle distance is badly wrong in Himachal — Shimla to Mandi is ~60 km straight
and ~145 km of road — so the estimate applies a winding factor and a terrain-derived
average speed rather than pretending a helicopter. Both are named constants, because
they are the knobs someone will want to tune against a real drive.

This is an estimate and the UI says so. Set `OSRM_MOCK_MODE=false` with `OSRM_BASE_URL`
pointing at an OSRM carrying an HP extract to get real road geometry.
"""

from __future__ import annotations

import math
import uuid

from app.adapters.base import Leg, RoutingAdapter

# Road km per straight-line km. Measured against three real HP pairs (Shimla-Mandi
# 60/145, Shimla-Kullu 95/235, Mandi-Kullu 38/70): the ratios are 2.4, 2.5 and 1.8.
# 2.2 sits inside that spread rather than flattering the shortest one.
WINDING_FACTOR = 2.2

# Average moving speed on a National/State Highway through this terrain, km/h. Not a
# speed limit — an ambulance's realistic door-to-door average including gradient,
# hairpins and oncoming traffic on single-lane stretches.
HILL_SPEED_KMH = 38.0

EARTH_RADIUS_KM = 6371.0


def haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lng1 = math.radians(a[0]), math.radians(a[1])
    lat2, lng2 = math.radians(b[0]), math.radians(b[1])
    dlat, dlng = lat2 - lat1, lng2 - lng1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlng / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(h))


class MockOsrm(RoutingAdapter):
    async def table(
        self, *, origin: tuple[float, float], destinations: list[tuple[uuid.UUID, float, float]]
    ) -> list[Leg]:
        legs = []
        for hospital_id, lat, lng in destinations:
            km = haversine_km(origin, (lat, lng)) * WINDING_FACTOR
            legs.append(
                Leg(
                    hospital_id=hospital_id,
                    km=round(km, 1),
                    minutes=round(km / HILL_SPEED_KMH * 60, 1),
                    mock=True,
                )
            )
        return legs

    async def health(self) -> bool:
        return True

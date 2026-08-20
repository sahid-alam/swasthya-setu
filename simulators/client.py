"""Shared HTTP client for every simulator.

Simulators are external clients. They authenticate and POST to the same public
`/api/v1/signals` endpoint real hardware uses, with the same payload — nothing here
touches the database or imports backend services. See
.claude/skills/signal-simulator/SKILL.md ("never inject signals directly").
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

import httpx

API = os.environ.get("SETU_API", "http://localhost:8000")
# A field gateway would carry its own device credential; the demo reuses the seeded
# admin so `make demo` needs no extra setup.
GATEWAY_PHONE = os.environ.get("SETU_SIM_PHONE", "9418000001")
GATEWAY_PASSWORD = os.environ.get("SETU_SIM_PASSWORD", "setu-admin")

SIM_SPEED = int(os.environ.get("SIM_SPEED", "1"))


@dataclass
class Signal:
    """One sighting, at `at` simulated seconds from the start of the run."""

    at: float
    source: str
    badge_id: str
    zone_code: str | None = None
    raw: dict = field(default_factory=dict)

    def payload(self) -> dict:
        return {
            "source": self.source,
            "badge_id": self.badge_id,
            "zone_code": self.zone_code,
            "raw": self.raw,
        }


class Setu:
    def __init__(self, base_url: str = API) -> None:
        self.http = httpx.Client(base_url=base_url, timeout=15.0)
        self.http.headers["Authorization"] = f"Bearer {self._login()}"

    def _login(self) -> str:
        r = self.http.post(
            "/api/v1/auth/token",
            data={"username": GATEWAY_PHONE, "password": GATEWAY_PASSWORD},
        )
        r.raise_for_status()
        return r.json()["access_token"]

    def send(self, signal: Signal) -> dict:
        r = self.http.post("/api/v1/signals", json=signal.payload())
        r.raise_for_status()
        return r.json()

    def face(self, embedding: list[float], zone_code: str | None = None) -> dict:
        r = self.http.post(
            "/api/v1/signals/face", json={"embedding": embedding, "zone_code": zone_code}
        )
        r.raise_for_status()
        return r.json()

    def override(self, doctor_id: str, state: str, reason: str) -> dict:
        r = self.http.post(
            f"/api/v1/presence/{doctor_id}/override", json={"state": state, "reason": reason}
        )
        r.raise_for_status()
        return r.json()

    def roster(self) -> dict:
        """Who exists, what badge they carry, which zones their hospital has."""
        r = self.http.get("/api/v1/simulation/roster")
        r.raise_for_status()
        return r.json()

    def close(self) -> None:
        self.http.close()

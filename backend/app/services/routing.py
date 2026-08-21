"""Golden Hour Router — PRD §M8, demo scope.

Given one emergency location, rank reachable facilities by drive time against what they
can actually do: a specialist who is present (M1), a free bed (M5), blood in the right
group (seeded SYNTHETIC — M6 is not built).

**This is decision support, not dispatch.** CLAUDE.md bans live 108 integration and
ambulance fleet tracking; nothing here moves a vehicle or tells anyone to. It ranks
hospitals and shows its reasoning.

The acceptance criterion is the *reasoning*, not the order: "skipped X: no neurosurgeon
present" is the sentence this has to be able to say. So every candidate gets a persisted
row — including the ones that were ruled out — and each carries the factors behind its
score. A ranking that silently omits a hospital cannot explain itself.

The honesty rule that matters most here is D15: only a **confident** presence state
removes availability. "We cannot see the neurosurgeon" is not "there is no neurosurgeon",
and this module never collapses the two — an unknown reads as unknown, and says so.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.factory import routing as routing_adapter
from app.models import (
    BedKind,
    BloodComponent,
    BloodGroup,
    BloodStock,
    Department,
    Doctor,
    DoctorStatus,
    EmergencyRequest,
    Hospital,
    PresenceState,
    RouteRanking,
)
from app.services import beds as bed_service
from app.services.availability import is_confident
from app.services.referrals import KIND_FOR_SPECIALTY

# What the score is made of. Specialist presence dominates on purpose: a free bed in a
# hospital with nobody to operate is not a trauma destination.
W_SPECIALIST, W_BEDS, W_BLOOD = 0.5, 0.3, 0.2

# Enough free beds / units of the needed group to stop being the binding constraint.
BEDS_ENOUGH = 3
BLOOD_ENOUGH = 4

# Ruled-out hospitals are still ranked and still returned — never quietly dropped —
# so the UI can show them with the reason. `viable` is what the UI reads to say so.


@dataclass
class Candidate:
    hospital_id: uuid.UUID
    hospital: str
    lat: float
    lng: float
    drive_minutes: float
    km: float
    mock_route: bool
    specialist: float = 0.0
    beds: float = 0.0
    blood: float = 0.0
    free_beds: int = 0
    blood_units: int = 0
    reasons: list[str] = field(default_factory=list)
    blood_synthetic: bool = True

    @property
    def capability(self) -> float:
        return W_SPECIALIST * self.specialist + W_BEDS * self.beds + W_BLOOD * self.blood

    @property
    def viable(self) -> bool:
        """Can this place actually take the case?

        Deliberately NOT "capability > 0": beds and blood would otherwise carry a
        hospital with no relevant specialist to the top of the list, which is how you
        send a head injury somewhere with an empty ICU and nobody to operate.
        """
        return self.specialist > 0 and self.free_beds > 0

    @property
    def effective_minutes(self) -> float:
        """Drive time stretched by how little the place can do.

        The PRD asks for "drive time x capability". Dividing keeps the unit as minutes,
        which is the only unit anyone in an emergency thinks in: a hospital 20 minutes
        away at half capability ranks like one 40 minutes away that can do everything.
        """
        return self.drive_minutes / max(self.capability, 0.05)


async def _specialist_factor(
    db: AsyncSession, hospital_id: uuid.UUID, specialty: str | None, candidate: Candidate
) -> float:
    """1.0 seen present, 0.5 on the roster but unseen, 0.0 not here or confidently away.

    Departments are hospital-scoped rows, so this asks "does *this* hospital have one",
    never "does the network have one somewhere".
    """
    if not specialty:
        candidate.reasons.append("no specialty requested — specialist not scored")
        return 1.0

    department = (
        await db.execute(
            select(Department).where(
                Department.hospital_id == hospital_id,
                func.lower(Department.name) == specialty.lower(),
            )
        )
    ).scalar_one_or_none()
    if department is None:
        candidate.reasons.append(f"no {specialty} department here")
        return 0.0

    rows = (
        await db.execute(
            select(Doctor, DoctorStatus)
            .outerjoin(DoctorStatus, DoctorStatus.doctor_id == Doctor.id)
            .where(Doctor.department_id == department.id)
        )
    ).all()
    if not rows:
        candidate.reasons.append(f"{specialty} department has no doctors")
        return 0.0

    present = [s for _, s in rows if s is not None and is_confident(s) and s.state in SEEN_HERE]
    if present:
        candidate.reasons.append(f"{specialty}: {len(present)} confirmed present")
        return 1.0

    confidently_away = [s for _, s in rows if s is not None and is_confident(s)]
    if len(confidently_away) == len(rows):
        candidate.reasons.append(f"every {specialty} doctor is confirmed unavailable")
        return 0.0

    # D15: we cannot see them, and that is not the same as their not being there.
    candidate.reasons.append(
        f"{specialty}: on the roster but presence unknown — not confirmed at the bedside"
    )
    return 0.5


SEEN_HERE = (
    PresenceState.PRESENT_IN_DEPT,
    PresenceState.PRESENT_ELSEWHERE,
    PresenceState.ON_ROUNDS,
)


async def rank(
    db: AsyncSession,
    *,
    lat: float,
    lng: float,
    specialty: str | None = None,
    blood_group: BloodGroup | None = None,
    description: str | None = None,
    created_by: uuid.UUID | None = None,
    persist: bool = True,
) -> tuple[EmergencyRequest, list[Candidate], int]:
    """Rank every hospital for one location. Returns (request, ranked, duration_ms)."""
    started = time.perf_counter()
    now = datetime.now(UTC)

    hospitals = (await db.execute(select(Hospital))).scalars().all()
    if not hospitals:
        raise ValueError("no hospitals to rank")

    request = EmergencyRequest(
        lat=lat,
        lng=lng,
        description=description,
        specialty_needed=specialty,
        created_by=created_by,
    )
    db.add(request)
    await db.flush()

    # One call for all of them: N sequential round trips would not survive the <3s claim.
    legs = await routing_adapter().table(
        origin=(lat, lng),
        destinations=[(h.id, float(h.lat), float(h.lng)) for h in hospitals],
    )
    by_hospital = {leg.hospital_id: leg for leg in legs}

    kind = KIND_FOR_SPECIALTY.get(specialty or "", BedKind.GENERAL)
    candidates: list[Candidate] = []

    for hospital in hospitals:
        leg = by_hospital.get(hospital.id)
        if leg is None:
            continue
        candidate = Candidate(
            hospital_id=hospital.id,
            hospital=hospital.name,
            lat=float(hospital.lat),
            lng=float(hospital.lng),
            drive_minutes=leg.minutes,
            km=leg.km,
            mock_route=leg.mock,
        )

        candidate.specialist = await _specialist_factor(db, hospital.id, specialty, candidate)

        candidate.free_beds = await bed_service.free_count(db, hospital.id, kind)
        candidate.beds = min(candidate.free_beds / BEDS_ENOUGH, 1.0)
        if candidate.free_beds == 0:
            candidate.reasons.append(f"no free {kind.value} bed")
        else:
            candidate.reasons.append(f"{candidate.free_beds} free {kind.value} bed(s)")

        if blood_group is not None:
            units = (
                await db.execute(
                    select(func.coalesce(func.sum(BloodStock.units), 0)).where(
                        BloodStock.hospital_id == hospital.id,
                        BloodStock.group == blood_group,
                        BloodStock.component.in_((BloodComponent.PRBC, BloodComponent.WHOLE)),
                    )
                )
            ).scalar_one()
            candidate.blood_units = int(units)
            candidate.blood = min(candidate.blood_units / BLOOD_ENOUGH, 1.0)
            label = blood_group.value.replace("_POS", "+").replace("_NEG", "-")
            candidate.reasons.append(
                f"{candidate.blood_units} unit(s) of {label} (SYNTHETIC)"
                if candidate.blood_units
                else f"no {label} in stock (SYNTHETIC)"
            )
        else:
            candidate.blood = 1.0

        candidates.append(candidate)

    # Viable first by effective minutes; the ruled-out still ranked, so they can be shown
    # with their reason rather than vanishing.
    candidates.sort(key=lambda c: (not c.viable, c.effective_minutes))
    duration_ms = int((time.perf_counter() - started) * 1000)

    if persist:
        for position, candidate in enumerate(candidates, start=1):
            db.add(
                RouteRanking(
                    emergency_request_id=request.id,
                    hospital_id=candidate.hospital_id,
                    rank=position,
                    drive_minutes=candidate.drive_minutes,
                    capability_score=round(candidate.capability, 3),
                    reasons={
                        "viable": candidate.viable,
                        "why": candidate.reasons,
                        "factors": {
                            "specialist": candidate.specialist,
                            "beds": candidate.beds,
                            "blood": candidate.blood,
                        },
                        "free_beds": candidate.free_beds,
                        "blood_units": candidate.blood_units,
                        "route_is_estimated": candidate.mock_route,
                        "ranked_at": now.isoformat(),
                        "duration_ms": duration_ms,
                    },
                )
            )
        await db.flush()

    return request, candidates, duration_ms

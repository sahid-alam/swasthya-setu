"""Multi-signal presence fusion — docs/ARCHITECTURE.md §Presence fusion design, PRD §M1.

The scoring core is a pure function so the judge-facing behaviours (decay, a stale
roster being overridden, a dead beacon degrading) are unit-testable without a database.
"""

import math
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import events
from app.config import get_settings
from app.models import (
    Doctor,
    DoctorStatus,
    PresenceSignal,
    PresenceState,
    PresenceTransition,
    Shift,
    ShiftKind,
    SignalSource,
    Zone,
    ZoneKind,
)

# --- tuning table -----------------------------------------------------------
# One place to change how much each source is believed and how fast it goes stale.
# Nothing below this block hardcodes a weight.

TRUST: dict[SignalSource, float] = {
    SignalSource.MANUAL: 1.0,
    SignalSource.FACE: 0.95,
    SignalSource.RFID: 0.9,
    SignalSource.BLE: 0.7,
    SignalSource.WIFI: 0.5,
    SignalSource.ROSTER: 0.3,
}

# Half-life-ish constant per source, in seconds. A BLE badge pings often, so silence
# means something quickly; a face check-in is a deliberate act and stays meaningful.
TAU_SECONDS: dict[SignalSource, float] = {
    SignalSource.BLE: 300,
    SignalSource.WIFI: 600,
    SignalSource.RFID: 900,
    SignalSource.FACE: 1800,
    SignalSource.MANUAL: 7200,
    SignalSource.ROSTER: 3600,
}

# Below this, no observation is strong enough to assert a state, so we fall back to
# what the roster implies — never to an optimistic PRESENT.
FLIP_THRESHOLD = 0.35
# A single source this trusted flips the state immediately; anything weaker has to
# win twice in a row. This is the anti-flicker rule.
HIGH_TRUST = 0.9
LOOKBACK = timedelta(hours=4)
# Repeated sightings in one place raise confidence a little, but must never let an
# hour of BLE pings outvote one fresh RFID tap at the theatre door — a doctor is in
# exactly one place, so locations are competing evidence, not additive evidence.
CORROBORATION = 0.05
MAX_CORROBORATION = 3


@dataclass(frozen=True)
class Observation:
    source: SignalSource
    state: PresenceState
    observed_at: datetime
    signal_id: str | None = None
    zone_id: str | None = None
    zone_code: str | None = None


@dataclass
class Fusion:
    state: PresenceState
    confidence: float
    zone_id: str | None
    evidence: dict = field(default_factory=dict)


def state_for_zone(
    kind: ZoneKind, zone_department_id: uuid.UUID | None, doctor_department_id: uuid.UUID
) -> PresenceState:
    """Where a badge was seen implies what the doctor is doing."""
    if kind == ZoneKind.OT:
        return PresenceState.IN_SURGERY
    if kind == ZoneKind.WARD:
        return PresenceState.ON_ROUNDS
    if kind == ZoneKind.OPD and zone_department_id == doctor_department_id:
        return PresenceState.PRESENT_IN_DEPT
    # another department's OPD, the gate, the lobby: on site, not where patients wait
    return PresenceState.PRESENT_ELSEWHERE


def state_for_shift(kind: ShiftKind | None) -> PresenceState | None:
    """What the roster claims. ON_CALL deliberately implies nothing — being on call
    is not being on site, and guessing there is how rosters lie in the first place."""
    return (
        {
            ShiftKind.LEAVE: PresenceState.ON_LEAVE,
            ShiftKind.SURGERY: PresenceState.IN_SURGERY,
            ShiftKind.WARD: PresenceState.ON_ROUNDS,
            ShiftKind.OPD: PresenceState.PRESENT_IN_DEPT,
        }.get(kind)
        if kind
        else PresenceState.OFF_SHIFT
    )


def decayed_score(obs: Observation, now: datetime, sim_speed: int = 1) -> float:
    """trust x exp(-dt/tau). Decay scales with SIM_SPEED so a compressed demo day
    ages signals at the same rate relative to simulated time."""
    tau = TAU_SECONDS[obs.source] / max(sim_speed, 1)
    dt = max((now - obs.observed_at).total_seconds(), 0.0)
    return TRUST[obs.source] * math.exp(-dt / tau)


def fuse(
    observations: list[Observation],
    roster_state: PresenceState | None,
    now: datetime,
    *,
    sim_speed: int = 1,
    current_state: PresenceState | None = None,
    current_confidence: float = 0.0,
    pending: dict | None = None,
) -> Fusion:
    """Score every candidate state, pick the winner, then apply hysteresis.

    `pending` carries the last near-miss across calls so "two consecutive wins" can
    be enforced without keeping the engine stateful.
    """
    contributors: list[dict] = []
    # per state: (best single score, how many observations support it, that zone)
    strongest: dict[PresenceState, tuple[float, int, str | None]] = {}

    all_obs = list(observations)
    if roster_state is not None:
        # The roster is just another observation, scored like the rest — that is what
        # lets a real badge ping outrank a stale roster instead of special-casing it.
        all_obs.append(Observation(source=SignalSource.ROSTER, state=roster_state, observed_at=now))

    for obs in all_obs:
        score = decayed_score(obs, now, sim_speed)
        best, count, zone = strongest.get(obs.state, (0.0, 0, None))
        strongest[obs.state] = (
            (score, count + 1, obs.zone_id) if score > best else (best, count + 1, zone)
        )
        contributors.append(
            {
                "signal_id": obs.signal_id,
                "source": obs.source.value,
                "state": obs.state.value,
                "zone_code": obs.zone_code,
                "score": round(score, 4),
                "age_seconds": round(max((now - obs.observed_at).total_seconds(), 0.0), 1),
            }
        )

    # Strength of a place = its best sighting, nudged up by corroboration.
    scores: dict[PresenceState, float] = {
        state: best * (1 + CORROBORATION * min(count - 1, MAX_CORROBORATION))
        for state, (best, count, _) in strongest.items()
    }

    # Trust decides whether a sighting is worth believing; recency decides which
    # believed sighting is the *current* one. A gate tap and an OPD ping a minute
    # later are not competing claims about now — the later one supersedes the earlier.
    # Ranking on trust alone would pin a doctor to the door they walked through.
    believable = [
        (o, sc)
        for o, sc in ((o, decayed_score(o, now, sim_speed)) for o in all_obs)
        if sc >= FLIP_THRESHOLD
    ]
    if believable:
        # a sighting that names a place beats one that only proves "somewhere on site"
        current, _ = max(
            believable, key=lambda pair: (pair[0].zone_id is not None, pair[0].observed_at, pair[1])
        )
        winner = current.state
        top = scores[winner]
    else:
        winner, top = PresenceState.UNKNOWN, 0.0

    # An admin override is a statement of fact, not another vote. Sensors accumulate,
    # so without this a badge left on a desk would outscore "he went home at noon".
    # It expires by decay like everything else (TAU_SECONDS[MANUAL]).
    overridden = False
    manual = [
        (decayed_score(o, now, sim_speed), o) for o in all_obs if o.source == SignalSource.MANUAL
    ]
    if manual:
        score, obs_ = max(manual, key=lambda pair: pair[0])
        if score >= FLIP_THRESHOLD:
            winner, top, overridden = obs_.state, score, True

    degraded = False
    if top < FLIP_THRESHOLD and not overridden:
        # Nothing is strong enough to assert. Say what the roster implies, honestly
        # labelled low-confidence, or admit we do not know.
        degraded = True
        winner = roster_state or PresenceState.UNKNOWN
        top = scores.get(winner, 0.0)

    # Confidence is the strength of the best evidence behind the winning state, not a
    # share of the vote: a roster-only guess must read as ~0.3 (and render as "30%" per
    # DESIGN.md §9d), never as 100% just because nothing contradicted it.
    confidence = round(min(top, 1.0), 3)

    # --- hysteresis ---------------------------------------------------------
    decisive = [
        c
        for c in contributors
        if c["state"] == winner.value and TRUST[SignalSource(c["source"])] >= HIGH_TRUST
    ]
    # Hysteresis exists to stop two *confident* states flickering. It must not be used
    # to defend a low-confidence guess: if the current state is only what the roster
    # implied, the first real observation above threshold should win immediately.
    guessing = current_confidence < FLIP_THRESHOLD
    next_pending: dict | None = None
    held = False
    if (
        current_state is not None
        and winner != current_state
        and not decisive
        and not degraded
        and not overridden
        and not guessing
    ):
        streak = (
            (pending or {}).get("count", 0) if (pending or {}).get("state") == winner.value else 0
        )
        if streak < 1:
            next_pending = {"state": winner.value, "count": streak + 1}
            winner = current_state
            held = True

    zone_id = strongest.get(winner, (0.0, 0, None))[2]
    evidence = {
        "candidates": {
            s.value: round(v, 4) for s, v in sorted(scores.items(), key=lambda kv: -kv[1])
        },
        "contributors": sorted(contributors, key=lambda c: -c["score"])[:12],
        "top_score": round(top, 4),
        "threshold": FLIP_THRESHOLD,
        "degraded_to_roster": degraded,
        "manual_override": overridden,
        "held_by_hysteresis": held,
        "roster_state": roster_state.value if roster_state else None,
        "sim_speed": sim_speed,
        "computed_at": now.isoformat(),
    }
    if next_pending:
        evidence["pending"] = next_pending

    return Fusion(state=winner, confidence=confidence, zone_id=zone_id, evidence=evidence)


# --- database layer ---------------------------------------------------------


async def roster_state_for(db: AsyncSession, doctor_id: uuid.UUID, now: datetime):
    shift = (
        await db.execute(
            select(Shift)
            .where(Shift.doctor_id == doctor_id, Shift.starts_at <= now, Shift.ends_at >= now)
            .order_by(Shift.starts_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return state_for_shift(shift.kind if shift else None)


async def observations_for(db: AsyncSession, doctor: Doctor, now: datetime) -> list[Observation]:
    rows = (
        await db.execute(
            select(PresenceSignal, Zone)
            .outerjoin(Zone, Zone.id == PresenceSignal.zone_id)
            .where(
                PresenceSignal.doctor_id == doctor.id,
                PresenceSignal.observed_at >= now - LOOKBACK,
                PresenceSignal.observed_at <= now,
            )
            .order_by(PresenceSignal.observed_at.desc())
            .limit(200)
        )
    ).all()

    out = []
    for signal, zone in rows:
        if zone is not None:
            state = state_for_zone(zone.kind, zone.department_id, doctor.department_id)
        elif signal.source == SignalSource.MANUAL:
            state = PresenceState(signal.raw.get("state", PresenceState.UNKNOWN.value))
        else:
            state = PresenceState.PRESENT_ELSEWHERE  # seen on the network, location unknown
        out.append(
            Observation(
                source=signal.source,
                state=state,
                observed_at=signal.observed_at,
                signal_id=str(signal.id),
                zone_id=str(zone.id) if zone else None,
                zone_code=zone.code if zone else None,
            )
        )
    return out


async def recompute(
    db: AsyncSession, doctor: Doctor, now: datetime | None = None, *, publish: bool = True
) -> tuple[DoctorStatus, bool]:
    """Re-fuse one doctor and persist. Returns (status, changed); a transition row is
    written only on a real change — that table is the evidence trail, not a log."""
    now = now or datetime.now(UTC)
    settings = get_settings()

    status = (
        await db.execute(select(DoctorStatus).where(DoctorStatus.doctor_id == doctor.id))
    ).scalar_one_or_none()

    result = fuse(
        await observations_for(db, doctor, now),
        await roster_state_for(db, doctor.id, now),
        now,
        sim_speed=settings.sim_speed,
        current_state=status.state if status else None,
        current_confidence=float(status.confidence) if status else 0.0,
        pending=(status.evidence or {}).get("pending") if status else None,
    )

    previous = status.state if status else None
    changed = previous != result.state

    if status is None:
        status = DoctorStatus(doctor_id=doctor.id, since=now)
        db.add(status)
    status.state = result.state
    status.confidence = result.confidence
    status.zone_id = uuid.UUID(result.zone_id) if result.zone_id else None
    status.evidence = result.evidence
    if changed:
        status.since = now
        db.add(
            PresenceTransition(
                doctor_id=doctor.id,
                from_state=previous or PresenceState.UNKNOWN,
                to_state=result.state,
                confidence=result.confidence,
                evidence=result.evidence,
                at=now,
            )
        )

    await db.flush()

    if changed and publish:
        await events.publish(
            "presence.changed",
            {
                "doctor_id": str(doctor.id),
                "hospital_id": str(doctor.hospital_id),
                "department_id": str(doctor.department_id),
                "old": previous.value if previous else None,
                "new": result.state.value,
                "confidence": result.confidence,
                "zone_id": result.zone_id,
                "at": now.isoformat(),
            },
        )
    return status, changed

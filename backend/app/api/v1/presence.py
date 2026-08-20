"""Presence ingestion and read API — PRD §M1.

`POST /signals` is the one door every signal comes through. Simulators and real
hardware send byte-identical payloads; the only difference is which one is plugged
in. Nothing writes presence tables directly (see .claude/skills/signal-simulator).
"""

import math
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import (
    Department,
    Doctor,
    DoctorStatus,
    Hospital,
    PresenceSignal,
    PresenceState,
    PresenceTransition,
    Shift,
    ShiftKind,
    SignalSource,
    User,
    UserRole,
    Zone,
)
from app.security import require_roles
from app.services import notify, scheduling
from app.services import presence as fusion

router = APIRouter(tags=["presence"])

# Cosine similarity above which a kiosk embedding is accepted as a known face.
# ArcFace-style embeddings sit near 0 for strangers, so this is deliberately strict.
FACE_MATCH_THRESHOLD = 0.45

GATEWAY = require_roles(UserRole.ADMIN, UserRole.STAFF)
ADMIN = require_roles(UserRole.ADMIN)


class SignalIn(BaseModel):
    """Exactly the payload in docs/ARCHITECTURE.md — hardware and simulator alike."""

    source: SignalSource
    badge_id: str
    zone_code: str | None = None
    observed_at: datetime | None = None
    raw: dict = Field(default_factory=dict)


class PresenceOut(BaseModel):
    doctor_id: str
    doctor_name: str
    badge_id: str
    department: str
    hospital: str
    state: PresenceState
    confidence: float
    zone_code: str | None = None
    since: datetime
    evidence: dict = Field(default_factory=dict)


class SignalAccepted(BaseModel):
    signal_id: str
    doctor_id: str
    state: PresenceState
    confidence: float
    changed: bool


class FaceCheckIn(BaseModel):
    embedding: list[float]
    zone_code: str | None = None
    observed_at: datetime | None = None


class FaceResult(BaseModel):
    matched: bool
    doctor_id: str | None = None
    doctor_name: str | None = None
    similarity: float
    state: PresenceState | None = None


class OverrideIn(BaseModel):
    state: PresenceState
    reason: str = Field(min_length=3, max_length=500)


async def _resolve(db: AsyncSession, badge_id: str, zone_code: str | None):
    doctor = (
        await db.execute(select(Doctor).where(Doctor.badge_id == badge_id))
    ).scalar_one_or_none()
    if doctor is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"unknown badge {badge_id}")

    zone = None
    if zone_code:
        zone = (
            await db.execute(
                select(Zone).where(Zone.hospital_id == doctor.hospital_id, Zone.code == zone_code)
            )
        ).scalar_one_or_none()
        if zone is None:
            # A reader reporting a zone this hospital does not have is a provisioning
            # bug — failing loudly beats silently recording a location-less sighting.
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"unknown zone {zone_code}")
    return doctor, zone


async def _ingest(
    db: AsyncSession,
    doctor: Doctor,
    zone: Zone | None,
    source: SignalSource,
    observed_at: datetime | None,
    raw: dict,
) -> tuple[PresenceSignal, DoctorStatus, bool]:
    observed_at = observed_at or datetime.now(UTC)
    if observed_at.tzinfo is None:
        observed_at = observed_at.replace(tzinfo=UTC)

    signal = PresenceSignal(
        doctor_id=doctor.id,
        source=source,
        zone_id=zone.id if zone else None,
        raw=raw,
        observed_at=observed_at,
        trust=fusion.TRUST[source],
    )
    db.add(signal)
    await db.flush()

    # Fuse at the later of now / observed_at so a backdated signal cannot look "fresh".
    status_row, changed = await fusion.recompute(db, doctor, max(observed_at, datetime.now(UTC)))

    # M1 -> M2: a confident contradiction of the roster re-seats the clinic list in the
    # same transaction, so presence and the plan can never disagree at rest. Runs inline
    # rather than off the pub/sub topic — one moving part, and it keeps the end-to-end
    # "<5s" claim measurable from a single request (worst case measured: 176 ms).
    if changed:
        plan = await scheduling.replan_if_unavailable(db, doctor, status_row)
        if plan is not None:
            # Telling people is part of the replan, not a follow-up job. A plan that
            # moved forty patients and told none of them is worse than no plan.
            await notify.notify_replan(db, plan)

    await db.commit()
    return signal, status_row, changed


@router.post("/signals", response_model=SignalAccepted, status_code=status.HTTP_201_CREATED)
async def ingest_signal(
    body: SignalIn, db: AsyncSession = Depends(get_db), _=Depends(GATEWAY)
) -> SignalAccepted:
    if body.source == SignalSource.FACE:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "face check-in goes to /signals/face with an embedding"
        )
    doctor, zone = await _resolve(db, body.badge_id, body.zone_code)
    signal, row, changed = await _ingest(db, doctor, zone, body.source, body.observed_at, body.raw)
    return SignalAccepted(
        signal_id=str(signal.id),
        doctor_id=str(doctor.id),
        state=row.state,
        confidence=float(row.confidence),
        changed=changed,
    )


def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


@router.post("/signals/face", response_model=FaceResult)
async def face_check_in(
    body: FaceCheckIn, db: AsyncSession = Depends(get_db), _=Depends(GATEWAY)
) -> FaceResult:
    """Voluntary kiosk check-in. Only doctors who enrolled are matchable, and only
    the embedding is ever compared — no image reaches this service (PRD §M1 privacy)."""
    candidates = (
        (await db.execute(select(Doctor).where(Doctor.face_embedding.isnot(None)))).scalars().all()
    )

    best, best_score = None, 0.0
    for doctor in candidates:
        score = cosine(body.embedding, doctor.face_embedding or [])
        if score > best_score:
            best, best_score = doctor, score

    if best is None or best_score < FACE_MATCH_THRESHOLD:
        return FaceResult(matched=False, similarity=round(best_score, 4))

    zone = None
    if body.zone_code:
        _, zone = await _resolve(db, best.badge_id, body.zone_code)
    _, row, _changed = await _ingest(
        db, best, zone, SignalSource.FACE, body.observed_at, {"similarity": round(best_score, 4)}
    )
    name = (await db.execute(select(User.name).where(User.id == best.user_id))).scalar_one()
    return FaceResult(
        matched=True,
        doctor_id=str(best.id),
        doctor_name=name,
        similarity=round(best_score, 4),
        state=row.state,
    )


@router.post("/presence/{doctor_id}/override", response_model=SignalAccepted)
async def override_presence(
    doctor_id: uuid.UUID,
    body: OverrideIn,
    db: AsyncSession = Depends(get_db),
    admin: dict = Depends(ADMIN),
) -> SignalAccepted:
    """Admin override. Recorded as a MANUAL signal carrying who did it and why, so
    the evidence trail explains a hand-set state the same way it explains a beacon."""
    doctor = (await db.execute(select(Doctor).where(Doctor.id == doctor_id))).scalar_one_or_none()
    if doctor is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown doctor")

    signal, row, changed = await _ingest(
        db,
        doctor,
        None,
        SignalSource.MANUAL,
        None,
        {"state": body.state.value, "reason": body.reason, "by_user_id": admin["sub"]},
    )
    return SignalAccepted(
        signal_id=str(signal.id),
        doctor_id=str(doctor.id),
        state=row.state,
        confidence=float(row.confidence),
        changed=changed,
    )


@router.get("/presence", response_model=list[PresenceOut])
async def presence_board(
    hospital_id: uuid.UUID | None = None,
    department_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(get_db),
    _=Depends(GATEWAY),
) -> list[PresenceOut]:
    q = (
        select(DoctorStatus, Doctor, User, Department, Hospital, Zone)
        .join(Doctor, Doctor.id == DoctorStatus.doctor_id)
        .join(User, User.id == Doctor.user_id)
        .join(Department, Department.id == Doctor.department_id)
        .join(Hospital, Hospital.id == Doctor.hospital_id)
        .outerjoin(Zone, Zone.id == DoctorStatus.zone_id)
    )
    if hospital_id:
        q = q.where(Doctor.hospital_id == hospital_id)
    if department_id:
        q = q.where(Doctor.department_id == department_id)

    return [
        PresenceOut(
            doctor_id=str(doc.id),
            doctor_name=user.name,
            badge_id=doc.badge_id,
            department=dept.name,
            hospital=hosp.name,
            state=st.state,
            confidence=float(st.confidence),
            zone_code=zone.code if zone else None,
            since=st.since,
            evidence=st.evidence or {},
        )
        for st, doc, user, dept, hosp, zone in (await db.execute(q)).all()
    ]


class TransitionOut(BaseModel):
    at: datetime
    from_state: PresenceState
    to_state: PresenceState
    confidence: float
    evidence: dict


@router.get("/presence/{doctor_id}/transitions", response_model=list[TransitionOut])
async def transitions(
    doctor_id: uuid.UUID,
    limit: int = Query(20, le=200),
    db: AsyncSession = Depends(get_db),
    _=Depends(GATEWAY),
) -> list[TransitionOut]:
    """The evidence trail. This endpoint is the answer to "how do you know?"."""
    rows = (
        (
            await db.execute(
                select(PresenceTransition)
                .where(PresenceTransition.doctor_id == doctor_id)
                .order_by(PresenceTransition.at.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return [
        TransitionOut(
            at=t.at,
            from_state=t.from_state,
            to_state=t.to_state,
            confidence=float(t.confidence),
            evidence=t.evidence or {},
        )
        for t in rows
    ]


class SimDoctor(BaseModel):
    doctor_id: str
    name: str
    badge_id: str
    hospital_code: str
    department: str
    specialty: str
    face_enrolled: bool


class SimZone(BaseModel):
    code: str
    kind: str
    hospital_code: str
    department: str | None = None


class SimRoster(BaseModel):
    doctors: list[SimDoctor]
    zones: list[SimZone]


@router.get("/simulation/roster", response_model=SimRoster)
async def simulation_roster(db: AsyncSession = Depends(get_db), _=Depends(GATEWAY)) -> SimRoster:
    """Discovery for simulators: which badges exist and which zone codes are valid.

    Real hardware is provisioned with these out-of-band; a simulator has to ask,
    and asking over the API keeps it an external client rather than a DB peer.
    Deliberately does not return face embeddings.
    """
    doctor_rows = (
        await db.execute(
            select(Doctor, User, Department, Hospital)
            .join(User, User.id == Doctor.user_id)
            .join(Department, Department.id == Doctor.department_id)
            .join(Hospital, Hospital.id == Doctor.hospital_id)
        )
    ).all()
    zone_rows = (
        await db.execute(
            select(Zone, Hospital, Department)
            .join(Hospital, Hospital.id == Zone.hospital_id)
            .outerjoin(Department, Department.id == Zone.department_id)
        )
    ).all()

    return SimRoster(
        doctors=[
            SimDoctor(
                doctor_id=str(doc.id),
                name=user.name,
                badge_id=doc.badge_id,
                hospital_code=hosp.code,
                department=dept.name,
                specialty=doc.specialty,
                face_enrolled=doc.face_enrolled,
            )
            for doc, user, dept, hosp in doctor_rows
        ],
        zones=[
            SimZone(
                code=zone.code,
                kind=zone.kind.value,
                hospital_code=hosp.code,
                department=dept.name if dept else None,
            )
            for zone, hosp, dept in zone_rows
        ],
    )


class RosterIn(BaseModel):
    badge_id: str
    kind: ShiftKind
    starts_at: datetime | None = None
    ends_at: datetime | None = None


class RosterOut(BaseModel):
    doctor_id: str
    kind: ShiftKind
    starts_at: datetime
    ends_at: datetime
    state: PresenceState
    confidence: float


@router.put("/roster/shift", response_model=RosterOut)
async def set_shift(
    body: RosterIn, db: AsyncSession = Depends(get_db), _=Depends(GATEWAY)
) -> RosterOut:
    """What an HMIS roster feed pushes. Replaces the shift covering the given window.

    This is what makes the roster *wrong* on purpose: set a doctor to LEAVE while
    their badge is still pinging, and the board should believe the badge (PRD §M1,
    "why not just an attendance app?").
    """
    doctor = (
        await db.execute(select(Doctor).where(Doctor.badge_id == body.badge_id))
    ).scalar_one_or_none()
    if doctor is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"unknown badge {body.badge_id}")

    now = datetime.now(UTC)
    starts_at = body.starts_at or now - timedelta(hours=1)
    ends_at = body.ends_at or now + timedelta(hours=5)

    overlapping = (
        (
            await db.execute(
                select(Shift).where(
                    Shift.doctor_id == doctor.id,
                    Shift.starts_at < ends_at,
                    Shift.ends_at > starts_at,
                )
            )
        )
        .scalars()
        .all()
    )
    for shift in overlapping:
        await db.delete(shift)
    await db.flush()

    db.add(
        Shift(
            doctor_id=doctor.id,
            department_id=doctor.department_id,
            starts_at=starts_at,
            ends_at=ends_at,
            kind=body.kind,
        )
    )
    await db.flush()

    row, _changed = await fusion.recompute(db, doctor, now)
    await db.commit()
    return RosterOut(
        doctor_id=str(doctor.id),
        kind=body.kind,
        starts_at=starts_at,
        ends_at=ends_at,
        state=row.state,
        confidence=float(row.confidence),
    )

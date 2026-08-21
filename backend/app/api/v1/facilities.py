"""Beds and referral reservation — PRD §M5.

Routers stay thin: every state change goes through `services/beds.py` or
`services/referrals.py`, so a bed can only leave FREE by one path.
"""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import (
    Bed,
    BedKind,
    BedState,
    BloodStock,
    Hospital,
    Patient,
    Referral,
    ReferralStatus,
    ReferralUrgency,
    User,
    UserRole,
)
from app.security import require_roles
from app.services import beds as bed_service
from app.services import referrals as referral_service

router = APIRouter(tags=["facilities"])

STAFF = require_roles(UserRole.ADMIN, UserRole.STAFF)


class WardOut(BaseModel):
    hospital_id: str
    hospital: str
    ward: str
    kind: BedKind
    free: int
    occupied: int
    reserved: int
    cleaning: int
    ooo: int
    total: int


@router.get("/beds/occupancy", response_model=list[WardOut])
async def occupancy(
    hospital_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(get_db),
    _=Depends(STAFF),
) -> list[WardOut]:
    return [
        WardOut(**{**w.__dict__, "total": w.total})
        for w in await bed_service.occupancy(db, hospital_id)
    ]


class BedOut(BaseModel):
    id: str
    hospital: str
    ward: str
    code: str
    kind: BedKind
    state: BedState


@router.get("/beds", response_model=list[BedOut])
async def list_beds(
    hospital_id: uuid.UUID | None = None,
    state: BedState | None = None,
    limit: int = Query(200, le=1000),
    db: AsyncSession = Depends(get_db),
    _=Depends(STAFF),
) -> list[BedOut]:
    q = select(Bed, Hospital).join(Hospital, Hospital.id == Bed.hospital_id)
    if hospital_id:
        q = q.where(Bed.hospital_id == hospital_id)
    if state:
        q = q.where(Bed.state == state)
    rows = (await db.execute(q.order_by(Hospital.name, Bed.ward, Bed.code).limit(limit))).all()
    return [
        BedOut(
            id=str(b.id),
            hospital=h.name,
            ward=b.ward,
            code=b.code,
            kind=b.kind,
            state=b.state,
        )
        for b, h in rows
    ]


class BedStateIn(BaseModel):
    state: BedState


@router.post("/beds/{bed_id}/state", response_model=BedOut)
async def set_bed_state(
    bed_id: uuid.UUID,
    body: BedStateIn,
    db: AsyncSession = Depends(get_db),
    _=Depends(STAFF),
) -> BedOut:
    """Ward staff moving a bed by hand — discharge, cleaning done, taken out of service.

    Releasing goes through the service so the open allocation is closed with it; a bed
    that reads FREE while an allocation still claims it is how double-booking starts.
    """
    row = (
        await db.execute(
            select(Bed, Hospital)
            .join(Hospital, Hospital.id == Bed.hospital_id)
            .where(Bed.id == bed_id)
        )
    ).one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such bed")
    bed, hospital = row

    if body.state is BedState.RESERVED:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "a bed is reserved by placing a referral, not by hand",
        )
    await bed_service.release(db, bed_id, to=body.state)
    await db.commit()
    await db.refresh(bed)
    return BedOut(
        id=str(bed.id),
        hospital=hospital.name,
        ward=bed.ward,
        code=bed.code,
        kind=bed.kind,
        state=bed.state,
    )


class ReferralOut(BaseModel):
    id: str
    from_hospital: str
    to_hospital: str
    patient_name: str
    specialty: str
    urgency: ReferralUrgency
    status: ReferralStatus
    bed: str | None
    expires_at: datetime | None
    notes: str | None


async def _describe(db: AsyncSession, referral: Referral) -> ReferralOut:
    src = (
        await db.execute(select(Hospital.name).where(Hospital.id == referral.from_hospital_id))
    ).scalar_one()
    dst = (
        await db.execute(select(Hospital.name).where(Hospital.id == referral.to_hospital_id))
    ).scalar_one()
    patient = (
        await db.execute(select(Patient.name).where(Patient.id == referral.patient_id))
    ).scalar_one()
    bed = await referral_service.bed_for(db, referral)
    return ReferralOut(
        id=str(referral.id),
        from_hospital=src,
        to_hospital=dst,
        patient_name=patient,
        specialty=referral.specialty,
        urgency=referral.urgency,
        status=referral.status,
        bed=f"{bed.ward} · {bed.code}" if bed else None,
        expires_at=referral.expires_at,
        notes=referral.notes,
    )


@router.get("/referrals", response_model=list[ReferralOut])
async def list_referrals(
    to_hospital_id: uuid.UUID | None = None,
    limit: int = Query(50, le=200),
    db: AsyncSession = Depends(get_db),
    _=Depends(STAFF),
) -> list[ReferralOut]:
    q = select(Referral).order_by(Referral.created_at.desc()).limit(limit)
    if to_hospital_id:
        q = q.where(Referral.to_hospital_id == to_hospital_id)
    rows = (await db.execute(q)).scalars().all()
    return [await _describe(db, r) for r in rows]


class ReferralIn(BaseModel):
    from_hospital_id: uuid.UUID
    to_hospital_id: uuid.UUID
    patient_id: uuid.UUID
    specialty: str
    urgency: ReferralUrgency = ReferralUrgency.URGENT
    notes: str | None = None


@router.post("/referrals", response_model=ReferralOut, status_code=status.HTTP_201_CREATED)
async def create_referral(
    body: ReferralIn,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(STAFF),
) -> ReferralOut:
    try:
        referral = await referral_service.request(
            db,
            from_hospital_id=body.from_hospital_id,
            to_hospital_id=body.to_hospital_id,
            patient_id=body.patient_id,
            specialty=body.specialty,
            urgency=body.urgency,
            notes=body.notes,
        )
    except referral_service.ReferralError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    await db.commit()
    return await _describe(db, referral)


@router.post("/referrals/{referral_id}/confirm", response_model=ReferralOut)
async def confirm_referral(
    referral_id: uuid.UUID, db: AsyncSession = Depends(get_db), _=Depends(STAFF)
) -> ReferralOut:
    try:
        referral = await referral_service.confirm(db, referral_id)
    except referral_service.ReferralError as exc:
        await db.commit()  # an expiry discovered mid-confirm is a real release; keep it
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    await db.commit()
    return await _describe(db, referral)


@router.post("/referrals/{referral_id}/cancel", response_model=ReferralOut)
async def cancel_referral(
    referral_id: uuid.UUID, db: AsyncSession = Depends(get_db), _=Depends(STAFF)
) -> ReferralOut:
    try:
        referral = await referral_service.cancel(db, referral_id)
    except referral_service.ReferralError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    await db.commit()
    return await _describe(db, referral)


class BloodOut(BaseModel):
    hospital: str
    group: str
    component: str
    units: int
    as_of: datetime
    source: str


@router.get("/blood", response_model=list[BloodOut])
async def blood(
    hospital_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(get_db),
    _=Depends(STAFF),
) -> list[BloodOut]:
    """Read-only stock, and every row carries its `source`.

    M6 — the real e-RaktKosh ingest — is NOT built. These rows are SYNTHETIC and say so,
    which is what the §9d SYNTHETIC DATA chip reads. They exist because M8's ranking
    needs a blood input; a number with no provenance in front of a judge is worse than
    no number at all.
    """
    q = select(BloodStock, Hospital).join(Hospital, Hospital.id == BloodStock.hospital_id)
    if hospital_id:
        q = q.where(BloodStock.hospital_id == hospital_id)
    rows = (await db.execute(q.order_by(Hospital.name, BloodStock.group))).all()
    return [
        BloodOut(
            hospital=h.name,
            group=s.group.value,
            component=s.component.value,
            units=s.units,
            as_of=s.as_of,
            source=s.source.value,
        )
        for s, h in rows
    ]

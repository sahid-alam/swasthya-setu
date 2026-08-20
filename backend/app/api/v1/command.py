"""Command-centre read API — PRD §M4."""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import UserRole
from app.security import require_roles
from app.services import alerts as alert_service

router = APIRouter(tags=["command"])
STAFF = require_roles(UserRole.ADMIN, UserRole.STAFF)


class AlertOut(BaseModel):
    kind: str
    severity: str
    title: str
    detail: str
    hospital: str
    department: str | None = None
    doctor_id: str | None = None
    department_id: str | None = None


class FacilityOut(BaseModel):
    hospital_id: str
    name: str
    code: str
    district: str
    level: str
    lat: float
    lng: float
    present: int
    doctors: int
    waiting: int
    alerts: int
    worst_severity: str | None = None


@router.get("/alerts", response_model=list[AlertOut])
async def alerts(
    hospital_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(get_db),
    _=Depends(STAFF),
) -> list[AlertOut]:
    """Sorted worst-first. Computed live rather than stored — a stored alert goes
    stale the moment the world moves, which is the failure this system exists to fix."""
    return [AlertOut(**vars(a)) for a in await alert_service.current(db, hospital_id)]


@router.get("/network", response_model=list[FacilityOut])
async def network(db: AsyncSession = Depends(get_db), _=Depends(STAFF)) -> list[FacilityOut]:
    """Facilities for the map: where they are, who is present, who is waiting."""
    return [FacilityOut(**row) for row in await alert_service.network(db)]


class DeptOut(BaseModel):
    id: str
    name: str
    hospital: str
    hospital_id: str
    waiting: int


@router.get("/departments", response_model=list[DeptOut])
async def departments(db: AsyncSession = Depends(get_db), _=Depends(STAFF)) -> list[DeptOut]:
    """Department list with live queue depth — what the queue view switches between."""
    from sqlalchemy import func, select

    from app.models import Appointment, AppointmentStatus, Department, Hospital, Slot

    rows = (
        await db.execute(
            select(Department, Hospital, func.count(Appointment.id))
            .join(Hospital, Hospital.id == Department.hospital_id)
            .outerjoin(
                Appointment,
                (Appointment.department_id == Department.id)
                & (Appointment.status == AppointmentStatus.BOOKED),
            )
            .outerjoin(Slot, (Slot.id == Appointment.slot_id) & (Slot.starts_at >= func.now()))
            .group_by(Department.id, Hospital.id)
            .order_by(Hospital.name, Department.name)
        )
    ).all()
    return [
        DeptOut(
            id=str(d.id),
            name=d.name,
            hospital=h.name,
            hospital_id=str(h.id),
            waiting=n,
        )
        for d, h, n in rows
    ]


class ServerTime(BaseModel):
    now: datetime


@router.get("/now", response_model=ServerTime)
async def server_now(_=Depends(STAFF)) -> ServerTime:
    """The dashboard shows "x minutes late"; it must measure that against the server's
    clock, not a presenter's laptop that might be minutes off."""
    from datetime import UTC

    return ServerTime(now=datetime.now(UTC))

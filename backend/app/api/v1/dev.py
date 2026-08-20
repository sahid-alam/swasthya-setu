"""Dev-only event injector. Lets /dev/ui prove the Redis -> WebSocket round-trip.
Phase 1D replaces this with the real scenario-triggers panel."""

import math
import random

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import events
from app.db import get_db
from app.models import Doctor, UserRole
from app.security import require_roles

router = APIRouter(prefix="/dev", tags=["dev"])


class PublishIn(BaseModel):
    topic: str = "alert.raised"
    payload: dict = {}


class PublishOut(BaseModel):
    published: bool
    topic: str


@router.post("/publish", response_model=PublishOut)
async def publish(body: PublishIn, _=Depends(require_roles(UserRole.ADMIN))) -> PublishOut:
    await events.publish(body.topic, body.payload)
    return PublishOut(published=True, topic=body.topic)


class FaceCapture(BaseModel):
    badge_id: str
    embedding: list[float]


@router.get("/face-capture/{badge_id}", response_model=FaceCapture)
async def face_capture(
    badge_id: str, db: AsyncSession = Depends(get_db), _=Depends(require_roles(UserRole.ADMIN))
) -> FaceCapture:
    """Stands in for a kiosk camera: returns the enrolled vector with noise added, so
    the simulator exercises real cosine matching rather than an exact-equality trick.

    Dev-only and admin-gated — enrolled embeddings are never served by the public API.
    """
    doctor = (
        await db.execute(select(Doctor).where(Doctor.badge_id == badge_id))
    ).scalar_one_or_none()
    if doctor is None or not doctor.face_embedding:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no enrolled face for that badge")

    rng = random.Random(badge_id)  # same badge -> same capture, so demos are repeatable
    noisy = [v + rng.gauss(0, 0.03) for v in doctor.face_embedding]
    norm = math.sqrt(sum(v * v for v in noisy)) or 1.0
    return FaceCapture(badge_id=badge_id, embedding=[round(v / norm, 6) for v in noisy])

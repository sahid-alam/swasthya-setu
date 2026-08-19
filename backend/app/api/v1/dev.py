"""Dev-only event injector. Lets /dev/ui prove the Redis -> WebSocket round-trip.
Phase 1D replaces this with the real scenario-triggers panel."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app import events
from app.models import UserRole
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

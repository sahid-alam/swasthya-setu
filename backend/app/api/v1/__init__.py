from fastapi import APIRouter

from app.api.v1 import auth, dev, health, presence, scheduling

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(presence.router)
api_router.include_router(scheduling.router)
api_router.include_router(dev.router)

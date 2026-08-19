from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import text

from app import events
from app.db import engine

router = APIRouter(tags=["health"])


class Health(BaseModel):
    status: str
    postgres: bool
    redis: bool


async def _ok(check) -> bool:
    try:
        await check()
        return True
    except Exception:
        return False


@router.get("/health", response_model=Health)
async def health() -> Health:
    async def pg():
        async with engine.connect() as conn:
            await conn.execute(text("select 1"))

    postgres, red = await _ok(pg), await _ok(events.client().ping)
    return Health(status="ok" if postgres and red else "degraded", postgres=postgres, redis=red)

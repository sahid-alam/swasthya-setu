from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import text

from app import events
from app.adapters.factory import mock_mode
from app.config import get_settings
from app.db import engine
from app.models import Channel

MOCKABLE = (Channel.SMS, Channel.WHATSAPP, Channel.TELEGRAM, Channel.EMAIL, Channel.IVR)

router = APIRouter(tags=["health"])


class Health(BaseModel):
    status: str
    postgres: bool
    redis: bool
    # Which adapters are mocked. Not a secret — the opposite: a client needs to know
    # before it does anything that would put real messages through a real SIM, and
    # `infra/demo_check.py` refuses to run the spine against a live SMS gateway.
    mocks: dict[str, bool]


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
    return Health(
        status="ok" if postgres and red else "degraded",
        postgres=postgres,
        redis=red,
        # `osrm` is not a Channel, so it is not in MOCKABLE — it still has to be
        # reportable, because a judge asking "are those real drive times?" gets
        # answered from this endpoint.
        mocks={c.value.lower(): mock_mode(c) for c in MOCKABLE}
        | {
            "osrm": get_settings().osrm_mock_mode,
            "eraktkosh": get_settings().eraktkosh_mock_mode,
        },
    )

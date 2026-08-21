import asyncio
import contextlib
import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1 import api_router
from app.api.v1 import ws as ws_routes
from app.config import get_settings
from app.services.presence_sweeper import sweep_forever
from app.services.referrals import expire_forever

log = logging.getLogger("swasthya")


@contextlib.asynccontextmanager
async def lifespan(_: FastAPI):
    """Presence has to decay whether or not anything is arriving — a beacon going
    flat produces silence, and silence must lower confidence, not preserve it."""
    settings = get_settings()
    seconds = settings.presence_sweep_seconds
    tasks = [asyncio.create_task(sweep_forever(seconds))] if seconds > 0 else []
    # M5: a reservation that only releases when a human remembers is not a reservation.
    if settings.referral_sweep_seconds > 0:
        tasks.append(asyncio.create_task(expire_forever(settings.referral_sweep_seconds)))
    if not settings.telegram_mock_mode:
        # Only in live mode: polling Telegram with no token would be a background task
        # failing every five seconds behind a demo that otherwise looks fine.
        from app.services.telegram_link import poll_forever

        tasks.append(asyncio.create_task(poll_forever()))
    yield
    for task in tasks:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


app = FastAPI(title="Swasthya-Setu", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(api_router)
app.include_router(ws_routes.router)


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception) -> JSONResponse:
    log.exception("unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "internal error"})

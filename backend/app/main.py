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

log = logging.getLogger("swasthya")


@contextlib.asynccontextmanager
async def lifespan(_: FastAPI):
    """Presence has to decay whether or not anything is arriving — a beacon going
    flat produces silence, and silence must lower confidence, not preserve it."""
    seconds = get_settings().presence_sweep_seconds
    task = asyncio.create_task(sweep_forever(seconds)) if seconds > 0 else None
    yield
    if task:
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

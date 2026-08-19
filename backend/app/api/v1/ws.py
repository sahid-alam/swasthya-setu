import asyncio
import contextlib

import jwt
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app import events
from app.security import decode_token

router = APIRouter()

STAFF_ROLES = {"ADMIN", "DOCTOR", "STAFF"}


@router.websocket("/ws/dashboard")
async def dashboard(ws: WebSocket, hospital_id: str | None = None, token: str | None = None):
    """Relays docs/ARCHITECTURE.md §Events topics. Nothing polls.

    Token rides the query string because browsers can't set headers on a WebSocket.
    """
    try:
        claims = decode_token(token or "")
    except jwt.PyJWTError:
        await ws.close(code=4401, reason="invalid token")
        return
    if claims.get("role") not in STAFF_ROLES:
        await ws.close(code=4403, reason="staff only")
        return

    await ws.accept()
    stream = events.subscribe(events.DASHBOARD_TOPICS)

    async def pump():
        async for msg in stream:
            payload_hospital = msg["payload"].get("hospital_id")
            if hospital_id and payload_hospital and payload_hospital != hospital_id:
                continue
            await ws.send_json(msg)

    task = asyncio.create_task(pump())
    try:
        while True:  # client sends nothing; this just detects disconnect
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        await stream.aclose()

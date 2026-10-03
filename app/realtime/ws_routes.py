import logging

import jwt
from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect, status
from fastapi.concurrency import run_in_threadpool
from pydantic import ValidationError

from app.core.errors import AppError
from app.core.security import decode_access_token
from app.db.session import SessionLocal
from app.realtime import sync_facade
from app.realtime.connection_manager import manager
from app.realtime.events import (
    PLAYBACK_EVENTS,
    ClientMessage,
    EventType,
    PlaybackPayload,
    ServerMessage,
)
from app.repositories import room_repo
from app.services import room_service

logger = logging.getLogger(__name__)
router = APIRouter()


def _authorize(room_id: str, user_id: int) -> dict | None:
    """REST join must happen before WebSocket connect. Returns the room snapshot or None."""
    with SessionLocal() as db:
        try:
            room = room_service.get_active_room_or_404(db, room_id)
        except AppError:
            return None
        if not room_repo.get_participant(db, room.id, user_id):
            return None
        return room_service.to_room_out(room).model_dump(mode="json")


def _persist_playback(room_id: str, event_type: EventType, payload: PlaybackPayload) -> None:
    with SessionLocal() as db:
        room_service.update_playback_state(
            db,
            room_id,
            is_playing={EventType.PLAY: True, EventType.PAUSE: False}.get(event_type),
            position_seconds=payload.position_seconds,
            current_song_id=payload.song_id if event_type == EventType.SONG_CHANGE else None,
        )


@router.websocket("/rooms/{room_id}/ws")
async def room_socket(websocket: WebSocket, room_id: str, token: str = Query(...)):
    room_id = room_id.upper()
    try:
        user_id = int(decode_access_token(token)["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    snapshot = await run_in_threadpool(_authorize, room_id, user_id)
    if snapshot is None:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await sync_facade.connect(room_id, user_id, websocket)
    await manager.send(websocket, ServerMessage(type=EventType.ROOM_STATE, payload=snapshot))
    await sync_facade.broadcast(room_id, EventType.USER_JOINED, {"user_id": user_id}, user_id)

    try:
        while True:
            raw = await websocket.receive_json()
            try:
                message = ClientMessage.model_validate(raw)
            except ValidationError:
                await manager.send(
                    websocket,
                    ServerMessage(type=EventType.ERROR, payload={"code": "INVALID_MESSAGE"}),
                )
                continue

            if message.type not in PLAYBACK_EVENTS:
                await manager.send(
                    websocket,
                    ServerMessage(type=EventType.ERROR, payload={"code": "EVENT_NOT_ALLOWED"}),
                )
                continue

            if not await sync_facade.validate_controller(room_id, user_id):
                await manager.send(
                    websocket,
                    ServerMessage(type=EventType.ERROR, payload={"code": "NOT_ROOM_CONTROLLER"}),
                )
                continue

            try:
                payload = PlaybackPayload.model_validate(message.payload)
            except ValidationError:
                await manager.send(
                    websocket,
                    ServerMessage(type=EventType.ERROR, payload={"code": "INVALID_PAYLOAD"}),
                )
                continue

            await run_in_threadpool(_persist_playback, room_id, message.type, payload)
            await sync_facade.broadcast(
                room_id, message.type, payload.model_dump(), sender_user_id=user_id
            )
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("Unexpected error in room socket %s", room_id)
    finally:
        await sync_facade.disconnect(room_id, websocket)
        await sync_facade.broadcast(
            room_id, EventType.USER_LEFT, {"user_id": user_id, "reason": "disconnected"}, user_id
        )

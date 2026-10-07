import json
import logging

import jwt
from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect, status
from fastapi.concurrency import run_in_threadpool
from pydantic import ValidationError

from app.core.errors import AppError, ErrorCode
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
    TimeSyncPayload,
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


def _apply_playback(room_id: str, user_id: int, event: EventType, payload: PlaybackPayload):
    """Persists the event through BE. Returns (broadcast_payload, None) or (None, error_code)."""
    with SessionLocal() as db:
        try:
            room = room_service.apply_playback_event(
                db,
                room_id,
                user_id=user_id,
                event=event.value,
                position_seconds=payload.position_seconds,
                song_id=payload.song_id,
            )
        except AppError as exc:
            return None, exc.code
        return room_service.playback_payload(room), None


async def _send_error(websocket: WebSocket, code: str) -> None:
    await manager.send(websocket, ServerMessage(type=EventType.ERROR, payload={"code": code}))


async def _receive_message(websocket: WebSocket) -> ClientMessage | None:
    """Next client message, or None if it is malformed (the socket stays open)."""
    message = await websocket.receive()
    if message["type"] == "websocket.disconnect":
        raise WebSocketDisconnect(message.get("code", status.WS_1000_NORMAL_CLOSURE))
    text = message.get("text")
    if text is None:
        return None
    try:
        return ClientMessage.model_validate(json.loads(text))
    except (json.JSONDecodeError, ValidationError):
        return None


async def _reject(websocket: WebSocket) -> None:
    # Accept first so browsers see close code 1008; a handshake rejection surfaces only as 1006.
    await websocket.accept()
    await websocket.close(code=status.WS_1008_POLICY_VIOLATION)


@router.websocket("/rooms/{room_id}/ws")
async def room_socket(websocket: WebSocket, room_id: str, token: str = Query("")):
    room_id = room_id.upper()
    try:
        user_id = int(decode_access_token(token)["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        await _reject(websocket)
        return

    async with sync_facade.room_lock(room_id):
        snapshot = await run_in_threadpool(_authorize, room_id, user_id)
        if snapshot is None:
            await _reject(websocket)
            return
        came_online = await sync_facade.connect(room_id, user_id, websocket)
        snapshot["online_user_ids"] = sync_facade.online_user_ids(room_id)
        await manager.send(websocket, ServerMessage(type=EventType.ROOM_STATE, payload=snapshot))
    if came_online:
        await sync_facade.broadcast(
            room_id, EventType.USER_JOINED, {"user_id": user_id}, user_id, exclude=websocket
        )

    try:
        while True:
            message = await _receive_message(websocket)
            if message is None:
                await _send_error(websocket, "INVALID_MESSAGE")
                continue
            if message.type == EventType.TIME_SYNC:
                try:
                    sync = TimeSyncPayload.model_validate(message.payload)
                except ValidationError:
                    await _send_error(websocket, "INVALID_PAYLOAD")
                    continue
                await manager.send(
                    websocket,
                    ServerMessage(type=EventType.TIME_SYNC, payload={"client_ts": sync.client_ts}),
                )
                continue
            if message.type not in PLAYBACK_EVENTS:
                await _send_error(websocket, "EVENT_NOT_ALLOWED")
                continue
            try:
                payload = PlaybackPayload.model_validate(message.payload)
            except ValidationError:
                await _send_error(websocket, "INVALID_PAYLOAD")
                continue
            if message.type == EventType.SONG_CHANGE and payload.song_id is None:
                await _send_error(websocket, "INVALID_PAYLOAD")
                continue

            async with sync_facade.room_lock(room_id):
                state, error = await run_in_threadpool(
                    _apply_playback, room_id, user_id, message.type, payload
                )
                if not error:
                    await manager.broadcast(
                        room_id,
                        ServerMessage(type=message.type, payload=state, sender_user_id=user_id),
                    )
            if error:
                await _send_error(websocket, error)
                if error in (ErrorCode.ROOM_CLOSED, ErrorCode.ROOM_NOT_FOUND):
                    await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
                    break
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("Unexpected error in room socket %s", room_id)
    finally:
        removed_user, went_offline = await sync_facade.disconnect(room_id, websocket)
        if removed_user is not None and went_offline:
            await sync_facade.broadcast(
                room_id,
                EventType.USER_LEFT,
                {"user_id": user_id, "reason": "disconnected"},
                user_id,
            )

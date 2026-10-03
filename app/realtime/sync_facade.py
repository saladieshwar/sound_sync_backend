"""Room-sync facade delivered by RT to BE: connect, disconnect, broadcast, validate_controller."""

from typing import Any

from fastapi import WebSocket
from fastapi.concurrency import run_in_threadpool

from app.db.session import SessionLocal
from app.realtime.connection_manager import manager
from app.realtime.events import EventType, ServerMessage
from app.repositories import room_repo


def _read_controller_id(room_id: str) -> int | None:
    with SessionLocal() as db:
        room = room_repo.get_by_id(db, room_id)
        return room.controller_user_id if room else None


async def connect(room_id: str, user_id: int, websocket: WebSocket) -> None:
    await websocket.accept()
    await manager.add(room_id, user_id, websocket)


async def disconnect(room_id: str, websocket: WebSocket) -> int | None:
    return await manager.remove(room_id, websocket)


async def broadcast(
    room_id: str,
    event_type: EventType,
    payload: dict[str, Any] | None = None,
    sender_user_id: int | None = None,
) -> None:
    await manager.broadcast(
        room_id,
        ServerMessage(type=event_type, payload=payload or {}, sender_user_id=sender_user_id),
    )


async def validate_controller(room_id: str, user_id: int) -> bool:
    """Server-side source of truth: reads controller_user_id from the DB, never the client."""
    return await run_in_threadpool(_read_controller_id, room_id) == user_id


async def close_room(room_id: str) -> None:
    await broadcast(room_id, EventType.ROOM_CLOSED)
    await manager.close_room(room_id)

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


async def connect(room_id: str, user_id: int, websocket: WebSocket) -> bool:
    """Accepts and registers the socket; returns True if the user just came online."""
    await websocket.accept()
    return await manager.add(room_id, user_id, websocket)


async def disconnect(room_id: str, websocket: WebSocket) -> tuple[int | None, bool]:
    """Returns (user_id, user_now_offline); user_id is None if the server already removed it."""
    return await manager.remove(room_id, websocket)


def online_user_ids(room_id: str) -> list[int]:
    return sorted(manager.connected_user_ids(room_id))


async def broadcast(
    room_id: str,
    event_type: EventType,
    payload: dict[str, Any] | None = None,
    sender_user_id: int | None = None,
    exclude: WebSocket | None = None,
) -> None:
    await manager.broadcast(
        room_id,
        ServerMessage(type=event_type, payload=payload or {}, sender_user_id=sender_user_id),
        exclude=exclude,
    )


async def validate_controller(room_id: str, user_id: int) -> bool:
    """Server-side source of truth: reads controller_user_id from the DB, never the client."""
    return await run_in_threadpool(_read_controller_id, room_id) == user_id


async def remove_user(room_id: str, user_id: int) -> None:
    """After a REST leave: the user's sockets are closed so they stop receiving room events."""
    await manager.close_user(room_id, user_id)


async def close_room(room_id: str) -> None:
    await broadcast(room_id, EventType.ROOM_CLOSED)
    await manager.close_room(room_id)

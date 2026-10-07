import asyncio
import logging
import weakref
from collections import defaultdict

from fastapi import WebSocket, status

from app.realtime.events import ServerMessage

logger = logging.getLogger(__name__)


class ConnectionManager:
    """In-memory registry of live sockets per room. Owned by RT.

    A user may have several sockets in one room (e.g. two tabs); presence is per user.
    """

    def __init__(self) -> None:
        self._rooms: dict[str, dict[WebSocket, int]] = defaultdict(dict)
        self._lock = asyncio.Lock()
        self._room_locks: weakref.WeakValueDictionary[str, asyncio.Lock] = (
            weakref.WeakValueDictionary()
        )

    def room_lock(self, room_id: str) -> asyncio.Lock:
        """Held while a room event is persisted and broadcast, and while a new socket reads its
        `room_state`, so every socket sees the room's events in the order they were committed and
        none falls between a snapshot and the first broadcast. Not re-entrant."""
        lock = self._room_locks.get(room_id)
        if lock is None:
            lock = asyncio.Lock()
            self._room_locks[room_id] = lock
        return lock

    async def add(self, room_id: str, user_id: int, websocket: WebSocket) -> bool:
        """Registers the socket; returns True if this is the user's first socket in the room."""
        async with self._lock:
            sockets = self._rooms[room_id]
            first = user_id not in sockets.values()
            sockets[websocket] = user_id
            return first

    async def remove(self, room_id: str, websocket: WebSocket) -> tuple[int | None, bool]:
        """Unregisters the socket. Returns (user_id, user_now_offline).

        user_id is None if the socket was already removed by the server (leave / room closed).
        """
        async with self._lock:
            sockets = self._rooms.get(room_id)
            if not sockets or websocket not in sockets:
                return None, False
            user_id = sockets.pop(websocket)
            if not sockets:
                self._rooms.pop(room_id, None)
            return user_id, user_id not in sockets.values()

    def connected_user_ids(self, room_id: str) -> set[int]:
        return set(self._rooms.get(room_id, {}).values())

    async def send(self, websocket: WebSocket, message: ServerMessage) -> None:
        await websocket.send_text(message.model_dump_json())

    async def broadcast(
        self, room_id: str, message: ServerMessage, exclude: WebSocket | None = None
    ) -> None:
        data = message.model_dump_json()
        dead: list[WebSocket] = []
        for ws in list(self._rooms.get(room_id, {})):
            if ws is exclude:
                continue
            try:
                await ws.send_text(data)
            except Exception:
                logger.warning("Dropping dead socket in room %s", room_id)
                dead.append(ws)
        for ws in dead:
            await self.remove(room_id, ws)

    async def _close(self, sockets: list[WebSocket], reason: str) -> None:
        for ws in sockets:
            try:
                await ws.close(code=status.WS_1000_NORMAL_CLOSURE, reason=reason)
            except Exception:
                pass

    async def close_user(self, room_id: str, user_id: int, reason: str = "left") -> None:
        """Closes every socket of `user_id` in the room (after a REST leave)."""
        async with self._lock:
            sockets = self._rooms.get(room_id, {})
            mine = [ws for ws, uid in sockets.items() if uid == user_id]
            for ws in mine:
                sockets.pop(ws)
            if not sockets:
                self._rooms.pop(room_id, None)
        await self._close(mine, reason)

    async def close_room(self, room_id: str) -> None:
        async with self._lock:
            sockets = list(self._rooms.pop(room_id, {}))
        await self._close(sockets, "room_closed")


manager = ConnectionManager()

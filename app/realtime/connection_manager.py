import asyncio
import logging
from collections import defaultdict

from fastapi import WebSocket

from app.realtime.events import ServerMessage

logger = logging.getLogger(__name__)


class ConnectionManager:
    """In-memory registry of live sockets per room. Owned by RT."""

    def __init__(self) -> None:
        self._rooms: dict[str, dict[WebSocket, int]] = defaultdict(dict)
        self._lock = asyncio.Lock()

    async def add(self, room_id: str, user_id: int, websocket: WebSocket) -> None:
        async with self._lock:
            self._rooms[room_id][websocket] = user_id

    async def remove(self, room_id: str, websocket: WebSocket) -> int | None:
        async with self._lock:
            sockets = self._rooms.get(room_id)
            if not sockets:
                return None
            user_id = sockets.pop(websocket, None)
            if not sockets:
                self._rooms.pop(room_id, None)
            return user_id

    def connected_user_ids(self, room_id: str) -> set[int]:
        return set(self._rooms.get(room_id, {}).values())

    async def send(self, websocket: WebSocket, message: ServerMessage) -> None:
        await websocket.send_text(message.model_dump_json())

    async def broadcast(self, room_id: str, message: ServerMessage) -> None:
        data = message.model_dump_json()
        dead: list[WebSocket] = []
        for ws in list(self._rooms.get(room_id, {})):
            try:
                await ws.send_text(data)
            except Exception:
                logger.warning("Dropping dead socket in room %s", room_id)
                dead.append(ws)
        for ws in dead:
            await self.remove(room_id, ws)

    async def close_room(self, room_id: str) -> None:
        async with self._lock:
            sockets = self._rooms.pop(room_id, {})
        for ws in sockets:
            try:
                await ws.close()
            except Exception:
                pass


manager = ConnectionManager()

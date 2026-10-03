"""WebSocket event contract (RT <-> FE/BE). See docs/websocket_contract.md.

Client -> server:  {"type": <EventType>, "payload": {...}}
Server -> client:  {"type": <EventType>, "payload": {...}, "sender_user_id": int | null, "server_ts": int}
"""

import enum
import time
from typing import Any

from pydantic import BaseModel, Field


class EventType(str, enum.Enum):
    # Playback events: only accepted from the current controller
    PLAY = "play"
    PAUSE = "pause"
    SEEK = "seek"
    SONG_CHANGE = "song_change"
    # Control + presence events: server-originated only
    ACCESS_TRANSFER = "access_transfer"
    USER_JOINED = "user_joined"
    USER_LEFT = "user_left"
    ROOM_STATE = "room_state"
    ROOM_CLOSED = "room_closed"
    ERROR = "error"


PLAYBACK_EVENTS = {EventType.PLAY, EventType.PAUSE, EventType.SEEK, EventType.SONG_CHANGE}


class ClientMessage(BaseModel):
    type: EventType
    payload: dict[str, Any] = Field(default_factory=dict)


class PlaybackPayload(BaseModel):
    position_seconds: float = Field(ge=0)
    song_id: int | None = None


class ServerMessage(BaseModel):
    type: EventType
    payload: dict[str, Any] = Field(default_factory=dict)
    sender_user_id: int | None = None
    server_ts: int = Field(default_factory=lambda: int(time.time() * 1000))

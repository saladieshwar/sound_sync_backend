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
    # Clock sync: any participant; answered only to the sender
    TIME_SYNC = "time_sync"
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
    position_seconds: float = Field(ge=0, le=86_400)
    song_id: int | None = None


class TimeSyncPayload(BaseModel):
    """Client clock reading (epoch ms) echoed back with the server's `server_ts`."""

    client_ts: float


# Codes sent in `error` payloads (server -> sender only).
WS_ERROR_CODES = (
    "INVALID_MESSAGE",  # not JSON / unknown type / missing fields
    "INVALID_PAYLOAD",  # bad position, or song_change without song_id
    "EVENT_NOT_ALLOWED",  # server-originated event type sent by a client
    "NOT_ROOM_CONTROLLER",  # sender is not the current controller
    "NO_CURRENT_SONG",  # play/pause/seek before any song_change
    "SONG_NOT_FOUND",  # song_change to an unknown song
    "ROOM_CLOSED",  # room closed meanwhile; socket is then closed
)


class ServerMessage(BaseModel):
    type: EventType
    payload: dict[str, Any] = Field(default_factory=dict)
    sender_user_id: int | None = None
    server_ts: int = Field(default_factory=lambda: int(time.time() * 1000))

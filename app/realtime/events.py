"""WebSocket event contract (RT <-> FE/BE). See docs/websocket_contract.md.

Client -> server:  {"type": <EventType>, "payload": {...}}
Server -> client:  {"type": <EventType>, "payload": {...}, "sender_user_id": int | null, "server_ts": int}
"""

import enum
import time
from typing import Any

from pydantic import BaseModel, Field, field_validator


class EventType(str, enum.Enum):
    # Playback events: only accepted from the current controller
    PLAY = "play"
    PAUSE = "pause"
    SEEK = "seek"
    SONG_CHANGE = "song_change"
    # Clock sync: any participant; answered only to the sender
    TIME_SYNC = "time_sync"
    # Group chat: any participant; broadcast to the whole room
    CHAT_MESSAGE = "chat_message"
    # Control + presence events: server-originated only
    ACCESS_TRANSFER = "access_transfer"
    USER_JOINED = "user_joined"
    USER_LEFT = "user_left"
    ROOM_STATE = "room_state"
    ROOM_CLOSED = "room_closed"
    ERROR = "error"


PLAYBACK_EVENTS = {EventType.PLAY, EventType.PAUSE, EventType.SEEK, EventType.SONG_CHANGE}
MAX_CHAT_TEXT_LENGTH = 300
RECENT_CHAT_LIMIT = 50
CHAT_MIN_INTERVAL_SECONDS = 1.0


class ClientMessage(BaseModel):
    type: EventType
    payload: dict[str, Any] = Field(default_factory=dict)


class PlaybackPayload(BaseModel):
    position_seconds: float = Field(ge=0, le=86_400)
    song_id: int | None = None


class TimeSyncPayload(BaseModel):
    """Client clock reading (epoch ms) echoed back with the server's `server_ts`."""

    client_ts: float


class ChatMessagePayload(BaseModel):
    """Client chat line. Leading/trailing whitespace is stripped; empty text is rejected."""

    text: str = Field(min_length=1, max_length=MAX_CHAT_TEXT_LENGTH)

    @field_validator("text", mode="before")
    @classmethod
    def _strip(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


# Codes sent in `error` payloads (server -> sender only).
WS_ERROR_CODES = (
    "INVALID_MESSAGE",  # not JSON / unknown type / missing fields
    "INVALID_PAYLOAD",  # bad position, song_change without song_id, or empty/overlong chat
    "EVENT_NOT_ALLOWED",  # server-originated event type sent by a client
    "NOT_ROOM_CONTROLLER",  # sender is not the current controller
    "NO_CURRENT_SONG",  # play/pause/seek before any song_change
    "SONG_NOT_FOUND",  # song_change to an unknown song
    "ROOM_CLOSED",  # room closed meanwhile; socket is then closed
    "RATE_LIMITED",  # chat sent too soon after the previous one
)


class ServerMessage(BaseModel):
    type: EventType
    payload: dict[str, Any] = Field(default_factory=dict)
    sender_user_id: int | None = None
    server_ts: int = Field(default_factory=lambda: int(time.time() * 1000))

import secrets
import string
from datetime import datetime, timezone

from fastapi import status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import AppError, ErrorCode
from app.models import MusicalRoom, RoomStatus
from app.repositories import room_repo, song_repo
from app.schemas.room import RoomOut

_ROOM_ID_ALPHABET = string.ascii_uppercase + string.digits
_ROOM_ID_LENGTH = 8

PLAY, PAUSE, SEEK, SONG_CHANGE = "play", "pause", "seek", "song_change"


def _generate_room_id(db: Session) -> str:
    while True:
        room_id = "".join(secrets.choice(_ROOM_ID_ALPHABET) for _ in range(_ROOM_ID_LENGTH))
        if not room_repo.get_by_id(db, room_id):
            return room_id


def join_link(room_id: str) -> str:
    return f"{settings.FRONTEND_BASE_URL.rstrip('/')}/room/{room_id}"


def to_room_out(room: MusicalRoom) -> RoomOut:
    out = RoomOut.model_validate(room)
    out.join_link = join_link(room.id)
    return out


def get_active_room_or_404(db: Session, room_id: str, *, for_update: bool = False) -> MusicalRoom:
    room = room_repo.get_by_id(db, room_id.upper(), for_update=for_update)
    if not room:
        raise AppError(ErrorCode.ROOM_NOT_FOUND, "Room not found", status.HTTP_404_NOT_FOUND)
    if room.status != RoomStatus.ACTIVE:
        raise AppError(ErrorCode.ROOM_CLOSED, "Room is closed", status.HTTP_410_GONE)
    return room


def require_participant(db: Session, room: MusicalRoom, user_id: int) -> None:
    if not room_repo.get_participant(db, room.id, user_id):
        raise AppError(
            ErrorCode.NOT_ROOM_PARTICIPANT,
            "You are not a participant of this room",
            status.HTTP_403_FORBIDDEN,
        )


def create_room(db: Session, *, name: str, admin_user_id: int) -> MusicalRoom:
    return room_repo.create(
        db, room_id=_generate_room_id(db), name=name, admin_user_id=admin_user_id
    )


def join_room(db: Session, room_id: str, user_id: int) -> MusicalRoom:
    """Idempotent: joining a room you are already in returns the room unchanged."""
    room = get_active_room_or_404(db, room_id)
    if not room_repo.get_participant(db, room.id, user_id):
        room_repo.add_participant(db, room.id, user_id)
        db.refresh(room)
    return room


def leave_room(db: Session, room_id: str, user_id: int) -> tuple[MusicalRoom, bool]:
    """Returns (room, room_closed).

    Product rule: if the room admin leaves, the room is closed for everyone.
    If the current controller (non-admin) leaves, control returns to the admin.
    """
    room = get_active_room_or_404(db, room_id, for_update=True)
    participant = room_repo.get_participant(db, room.id, user_id)
    if not participant:
        raise AppError(
            ErrorCode.NOT_ROOM_PARTICIPANT,
            "You are not a participant of this room",
            status.HTTP_403_FORBIDDEN,
        )

    if user_id == room.admin_user_id:
        room.status = RoomStatus.CLOSED
        room.is_playing = False
        room.participants.clear()
        return room_repo.save(db, room), True

    room.participants.remove(participant)
    if room.controller_user_id == user_id:
        room.controller_user_id = room.admin_user_id
    return room_repo.save(db, room), False


def transfer_access(
    db: Session, room_id: str, *, requester_id: int, target_user_id: int
) -> MusicalRoom:
    """Only the room admin or the current controller can hand off control."""
    room = get_active_room_or_404(db, room_id, for_update=True)
    if requester_id not in (room.admin_user_id, room.controller_user_id):
        raise AppError(
            ErrorCode.NOT_ROOM_CONTROLLER,
            "Only the admin or current controller can transfer access",
            status.HTTP_403_FORBIDDEN,
        )
    require_participant(db, room, target_user_id)
    room.controller_user_id = target_user_id
    return room_repo.save(db, room)


def apply_playback_event(
    db: Session,
    room_id: str,
    *,
    user_id: int,
    event: str,
    position_seconds: float,
    song_id: int | None = None,
) -> MusicalRoom:
    """Validates and persists one playback event from the RT layer (atomic with the row lock).

    The controller check reads `controller_user_id` from the DB on every event, so a transfer
    that commits first always wins. Positions are clamped to the song length.
    """
    room = get_active_room_or_404(db, room_id, for_update=True)
    if room.controller_user_id != user_id:
        raise AppError(
            ErrorCode.NOT_ROOM_CONTROLLER,
            "Only the current controller can change playback",
            status.HTTP_403_FORBIDDEN,
        )

    if event == SONG_CHANGE:
        song = song_repo.get_by_id(db, song_id) if song_id is not None else None
        if song is None:
            raise AppError(ErrorCode.SONG_NOT_FOUND, "Song not found", status.HTTP_404_NOT_FOUND)
        room.current_song_id = song.id
        room.is_playing = True
    else:
        if room.current_song_id is None:
            raise AppError(
                ErrorCode.NO_CURRENT_SONG,
                "Pick a song before using playback controls",
                status.HTTP_409_CONFLICT,
            )
        song = song_repo.get_by_id(db, room.current_song_id)
        if event == PLAY:
            room.is_playing = True
        elif event == PAUSE:
            room.is_playing = False

    duration = float(song.duration_seconds or 0)
    position = max(position_seconds, 0.0)
    room.position_seconds = min(position, duration) if duration > 0 else position
    room.state_updated_at = datetime.now(timezone.utc)
    return room_repo.save(db, room)


def playback_payload(room: MusicalRoom) -> dict:
    """Canonical playback state broadcast to every client after an accepted event."""
    return {
        "song_id": room.current_song_id,
        "position_seconds": room.position_seconds,
        "is_playing": room.is_playing,
    }

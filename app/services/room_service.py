import secrets
import string
from datetime import datetime, timezone

from fastapi import status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import AppError, ErrorCode
from app.models import MusicalRoom, RoomStatus
from app.repositories import room_repo
from app.schemas.room import RoomOut

_ROOM_ID_ALPHABET = string.ascii_uppercase + string.digits
_ROOM_ID_LENGTH = 8


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


def get_active_room_or_404(db: Session, room_id: str) -> MusicalRoom:
    room = room_repo.get_by_id(db, room_id.upper())
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
    room = get_active_room_or_404(db, room_id)
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

    room_repo.remove_participant(db, participant)
    if room.controller_user_id == user_id:
        room.controller_user_id = room.admin_user_id
    return room_repo.save(db, room), False


def transfer_access(
    db: Session, room_id: str, *, requester_id: int, target_user_id: int
) -> MusicalRoom:
    """Only the room admin or the current controller can hand off control."""
    room = get_active_room_or_404(db, room_id)
    if requester_id not in (room.admin_user_id, room.controller_user_id):
        raise AppError(
            ErrorCode.NOT_ROOM_CONTROLLER,
            "Only the admin or current controller can transfer access",
            status.HTTP_403_FORBIDDEN,
        )
    require_participant(db, room, target_user_id)
    room.controller_user_id = target_user_id
    return room_repo.save(db, room)


def update_playback_state(
    db: Session,
    room_id: str,
    *,
    is_playing: bool | None = None,
    position_seconds: float | None = None,
    current_song_id: int | None = None,
) -> MusicalRoom:
    """Called by the RT layer to persist live playback state through BE/DATA."""
    room = get_active_room_or_404(db, room_id)
    if is_playing is not None:
        room.is_playing = is_playing
    if position_seconds is not None:
        room.position_seconds = position_seconds
    if current_song_id is not None:
        room.current_song_id = current_song_id
    room.state_updated_at = datetime.now(timezone.utc)
    return room_repo.save(db, room)

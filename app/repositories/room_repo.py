from datetime import datetime, timezone

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.models import MusicalRoom, RoomMessage, RoomParticipant, RoomStatus


def get_by_id(db: Session, room_id: str, *, for_update: bool = False) -> MusicalRoom | None:
    """`for_update` locks the row so controller checks and state writes are atomic."""
    return db.get(MusicalRoom, room_id, with_for_update=for_update, populate_existing=for_update)


def list_active(db: Session) -> list[MusicalRoom]:
    stmt = (
        select(MusicalRoom)
        .where(MusicalRoom.status == RoomStatus.ACTIVE)
        .order_by(MusicalRoom.created_at.desc())
    )
    return list(db.scalars(stmt))


def list_active_for_user(db: Session, user_id: int) -> list[MusicalRoom]:
    """Active rooms the user has joined, newest first."""
    stmt = (
        select(MusicalRoom)
        .join(RoomParticipant, RoomParticipant.room_id == MusicalRoom.id)
        .where(RoomParticipant.user_id == user_id, MusicalRoom.status == RoomStatus.ACTIVE)
        .order_by(MusicalRoom.created_at.desc())
    )
    return list(db.scalars(stmt).unique())


def create(db: Session, *, room_id: str, name: str, admin_user_id: int) -> MusicalRoom:
    room = MusicalRoom(
        id=room_id,
        name=name,
        admin_user_id=admin_user_id,
        controller_user_id=admin_user_id,
    )
    room.participants.append(RoomParticipant(user_id=admin_user_id))
    db.add(room)
    db.commit()
    db.refresh(room)
    return room


def get_participant(db: Session, room_id: str, user_id: int) -> RoomParticipant | None:
    return db.get(RoomParticipant, (room_id, user_id))


def add_participant(db: Session, room_id: str, user_id: int) -> RoomParticipant:
    participant = RoomParticipant(room_id=room_id, user_id=user_id)
    db.add(participant)
    db.commit()
    db.refresh(participant)
    return participant


def stop_rooms_playing(db: Session, song_id: int) -> list[str]:
    """Active rooms on `song_id` drop it and stop at 0 (not committed). Returns their IDs."""
    stmt = (
        update(MusicalRoom)
        .where(MusicalRoom.current_song_id == song_id, MusicalRoom.status == RoomStatus.ACTIVE)
        .values(
            current_song_id=None,
            is_playing=False,
            position_seconds=0.0,
            state_updated_at=datetime.now(timezone.utc),
        )
        .returning(MusicalRoom.id)
    )
    return list(db.scalars(stmt))


def save(db: Session, room: MusicalRoom) -> MusicalRoom:
    db.add(room)
    db.commit()
    db.refresh(room)
    return room


def add_message(db: Session, *, room_id: str, user_id: int, text: str) -> RoomMessage:
    message = RoomMessage(room_id=room_id, user_id=user_id, text=text)
    db.add(message)
    db.commit()
    db.refresh(message)
    return message


def list_recent_messages(db: Session, room_id: str, *, limit: int = 50) -> list[RoomMessage]:
    """Newest `limit` messages, returned oldest-first for chat display."""
    stmt = (
        select(RoomMessage)
        .where(RoomMessage.room_id == room_id)
        .order_by(RoomMessage.created_at.desc(), RoomMessage.id.desc())
        .limit(limit)
    )
    return list(reversed(list(db.scalars(stmt))))


def delete_messages_for_room(db: Session, room_id: str) -> None:
    db.execute(delete(RoomMessage).where(RoomMessage.room_id == room_id))
    db.commit()

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import MusicalRoom, RoomParticipant, RoomStatus


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


def save(db: Session, room: MusicalRoom) -> MusicalRoom:
    db.add(room)
    db.commit()
    db.refresh(room)
    return room

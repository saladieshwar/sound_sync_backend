import enum
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    String,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.user import User


class RoomStatus(str, enum.Enum):
    ACTIVE = "active"
    CLOSED = "closed"


class MusicalRoom(Base):
    __tablename__ = "musical_rooms"
    __table_args__ = (
        # Active-room listing (admin view), newest first (migration 0005).
        Index(
            "ix_musical_rooms_active_created_at",
            text("created_at DESC"),
            postgresql_where=text("status = 'active'"),
        ),
    )

    # Short, human-shareable Room ID (also used in the join link)
    id: Mapped[str] = mapped_column(String(12), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    admin_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    controller_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    current_song_id: Mapped[int | None] = mapped_column(
        ForeignKey("songs.id", ondelete="SET NULL"), index=True
    )
    is_playing: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    position_seconds: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    state_updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    status: Mapped[RoomStatus] = mapped_column(
        Enum(RoomStatus, name="room_status", values_callable=lambda e: [m.value for m in e]),
        default=RoomStatus.ACTIVE,
        nullable=False,
    )
    # clock_timestamp() so rooms created in one transaction still sort newest-first (migration 0005).
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.clock_timestamp(), nullable=False
    )

    participants: Mapped[list["RoomParticipant"]] = relationship(
        back_populates="room", cascade="all, delete-orphan", lazy="selectin"
    )


class RoomParticipant(Base):
    __tablename__ = "room_participants"

    room_id: Mapped[str] = mapped_column(
        ForeignKey("musical_rooms.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    room: Mapped[MusicalRoom] = relationship(back_populates="participants")
    user: Mapped[User] = relationship(lazy="joined")

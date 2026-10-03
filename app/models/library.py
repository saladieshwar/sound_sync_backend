from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.song import Song

# clock_timestamp() (not now()) so rows written in one transaction still get distinct,
# correctly ordered timestamps.


class LikedSong(Base):
    __tablename__ = "liked_songs"
    __table_args__ = (
        Index("ix_liked_songs_user_liked_at", "user_id", "liked_at"),
        Index("ix_liked_songs_song_id", "song_id"),
    )

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    song_id: Mapped[int] = mapped_column(
        ForeignKey("songs.id", ondelete="CASCADE"), primary_key=True
    )
    liked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.clock_timestamp(), nullable=False
    )

    song: Mapped[Song] = relationship(lazy="joined")


class RecentlyPlayed(Base):
    __tablename__ = "recently_played"
    __table_args__ = (
        # Matches library_repo.list_recently_played (WHERE user_id ORDER BY played_at DESC, id DESC
        # LIMIT n) so the newest-first page is read straight off the index with no sort.
        Index(
            "ix_recently_played_user_played_at_id",
            "user_id",
            text("played_at DESC"),
            text("id DESC"),
        ),
        Index("ix_recently_played_song_id", "song_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    song_id: Mapped[int] = mapped_column(
        ForeignKey("songs.id", ondelete="CASCADE"), nullable=False
    )
    played_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.clock_timestamp(), nullable=False
    )

    song: Mapped[Song] = relationship(lazy="joined")

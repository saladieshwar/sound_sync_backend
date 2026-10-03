from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Song(Base):
    __tablename__ = "songs"
    __table_args__ = (
        # Trigram indexes serve the substring ILIKE search (requires pg_trgm, migration 0003).
        Index("ix_songs_title_trgm", "title", postgresql_using="gin",
              postgresql_ops={"title": "gin_trgm_ops"}),
        Index("ix_songs_artist_trgm", "artist", postgresql_using="gin",
              postgresql_ops={"artist": "gin_trgm_ops"}),
        Index("ix_songs_album_trgm", "album", postgresql_using="gin",
              postgresql_ops={"album": "gin_trgm_ops"}),
        Index("ix_songs_category_lower", text("lower(category)")),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(200), index=True, nullable=False)
    artist: Mapped[str] = mapped_column(String(200), index=True, nullable=False)
    album: Mapped[str | None] = mapped_column(String(200), index=True)
    category: Mapped[str] = mapped_column(String(50), index=True, nullable=False)
    duration_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    audio_url: Mapped[str] = mapped_column(String(500), nullable=False)
    cover_url: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

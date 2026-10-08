from datetime import datetime

from sqlalchemy import Computed, DateTime, Index, Integer, String, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

# Must match migration 0005. chr(31) keeps a search term from matching across two fields.
SEARCH_TEXT_SQL = "lower(title || chr(31) || artist || chr(31) || coalesce(album, ''))"


class Song(Base):
    __tablename__ = "songs"
    __table_args__ = (
        # Trigram index serves the substring search (requires pg_trgm, migrations 0003/0005).
        Index("ix_songs_search_trgm", "search_text", postgresql_using="gin",
              postgresql_ops={"search_text": "gin_trgm_ops"}),
        Index("ix_songs_category_lower", text("lower(category)")),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(200), index=True, nullable=False)
    artist: Mapped[str] = mapped_column(String(200), index=True, nullable=False)
    album: Mapped[str | None] = mapped_column(String(200), index=True)
    music_director: Mapped[str | None] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(50), index=True, nullable=False)
    duration_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    audio_url: Mapped[str] = mapped_column(String(500), nullable=False)
    cover_url: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    search_text: Mapped[str] = mapped_column(
        Text, Computed(SEARCH_TEXT_SQL, persisted=True), nullable=False, deferred=True
    )

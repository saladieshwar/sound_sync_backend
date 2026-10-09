from datetime import datetime

from sqlalchemy import DateTime, Integer, LargeBinary, String, func
from sqlalchemy.orm import Mapped, deferred, mapped_column

from app.db.base import Base


class MediaFile(Base):
    """An uploaded file kept in the database (MEDIA_STORAGE=database), served from /media/<key>."""

    __tablename__ = "media_files"

    key: Mapped[str] = mapped_column(String(300), primary_key=True)  # e.g. "audio/<uuid>.mp3"
    content_type: Mapped[str] = mapped_column(String(100), nullable=False)
    size: Mapped[int] = mapped_column(Integer, nullable=False)
    data: Mapped[bytes] = deferred(mapped_column(LargeBinary, nullable=False))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

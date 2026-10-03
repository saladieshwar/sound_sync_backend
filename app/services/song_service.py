from fastapi import status
from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.models import Song
from app.repositories import song_repo


def get_song_or_404(db: Session, song_id: int) -> Song:
    song = song_repo.get_by_id(db, song_id)
    if not song:
        raise AppError(ErrorCode.SONG_NOT_FOUND, "Song not found", status.HTTP_404_NOT_FOUND)
    return song

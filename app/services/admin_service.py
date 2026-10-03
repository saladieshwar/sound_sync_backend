import shutil
import uuid
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import Song
from app.repositories import song_repo


def _store_file(upload: UploadFile, subdir: str) -> str:
    """Saves an upload to self-hosted media storage and returns its public URL."""
    target_dir = Path(settings.MEDIA_ROOT) / subdir
    target_dir.mkdir(parents=True, exist_ok=True)
    suffix = Path(upload.filename or "").suffix
    filename = f"{uuid.uuid4().hex}{suffix}"
    with (target_dir / filename).open("wb") as out:
        shutil.copyfileobj(upload.file, out)
    return f"{settings.MEDIA_URL_PREFIX}/{subdir}/{filename}"


def upload_song(
    db: Session,
    *,
    title: str,
    artist: str,
    album: str | None,
    category: str,
    duration_seconds: int,
    audio_file: UploadFile,
    cover_file: UploadFile | None,
) -> Song:
    audio_url = _store_file(audio_file, "audio")
    cover_url = _store_file(cover_file, "covers") if cover_file else None
    return song_repo.create(
        db,
        title=title,
        artist=artist,
        album=album,
        category=category,
        duration_seconds=duration_seconds,
        audio_url=audio_url,
        cover_url=cover_url,
    )

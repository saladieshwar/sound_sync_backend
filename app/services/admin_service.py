import uuid
from pathlib import Path

from fastapi import UploadFile, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import AppError, ErrorCode
from app.models import Song
from app.repositories import song_repo

# Files are served by extension (StaticFiles), so the allow-list is what keeps an upload from
# being served as HTML/JS/SVG on the API origin.
AUDIO_EXTENSIONS = {".mp3", ".wav", ".ogg", ".oga", ".opus", ".m4a", ".aac", ".flac", ".webm"}
COVER_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
_CHUNK = 1024 * 1024


def _check_extension(upload: UploadFile, allowed: set[str], field: str) -> str:
    suffix = Path(upload.filename or "").suffix.lower()
    if suffix not in allowed:
        raise AppError(
            ErrorCode.UNSUPPORTED_FILE_TYPE,
            f"{field} must be one of: {', '.join(sorted(allowed))}",
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            {"field": field, "allowed": sorted(allowed)},
        )
    return suffix


def _store_file(upload: UploadFile, subdir: str, suffix: str, max_bytes: int, field: str) -> Path:
    """Streams an upload into MEDIA_ROOT/subdir under a random name; enforces `max_bytes`."""
    target_dir = Path(settings.MEDIA_ROOT) / subdir
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / f"{uuid.uuid4().hex}{suffix}"
    written = 0
    try:
        with path.open("wb") as out:
            while chunk := upload.file.read(_CHUNK):
                written += len(chunk)
                if written > max_bytes:
                    raise AppError(
                        ErrorCode.FILE_TOO_LARGE,
                        f"{field} is larger than {max_bytes // (1024 * 1024)} MB",
                        status.HTTP_413_CONTENT_TOO_LARGE,
                        {"field": field, "max_bytes": max_bytes},
                    )
                out.write(chunk)
        if written == 0:
            raise AppError(
                ErrorCode.VALIDATION_ERROR,
                f"{field} is empty",
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                {"field": field},
            )
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return path


def _public_url(path: Path, subdir: str) -> str:
    return f"{settings.MEDIA_URL_PREFIX}/{subdir}/{path.name}"


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
    audio_suffix = _check_extension(audio_file, AUDIO_EXTENSIONS, "audio_file")
    has_cover = cover_file is not None and bool(cover_file.filename)
    cover_suffix = _check_extension(cover_file, COVER_EXTENSIONS, "cover_file") if has_cover else None

    stored: list[Path] = []
    try:
        audio_path = _store_file(audio_file, "audio", audio_suffix, settings.MAX_AUDIO_UPLOAD_BYTES, "audio_file")
        stored.append(audio_path)
        cover_url = None
        if has_cover:
            cover_path = _store_file(
                cover_file, "covers", cover_suffix, settings.MAX_COVER_UPLOAD_BYTES, "cover_file"
            )
            stored.append(cover_path)
            cover_url = _public_url(cover_path, "covers")
        return song_repo.create(
            db,
            title=title,
            artist=artist,
            album=album or None,
            category=category,
            duration_seconds=duration_seconds,
            audio_url=_public_url(audio_path, "audio"),
            cover_url=cover_url,
        )
    except BaseException:
        for path in stored:
            path.unlink(missing_ok=True)
        raise


def _media_path(url: str | None) -> Path | None:
    """Local file behind a `/media/...` URL, only if it resolves inside MEDIA_ROOT."""
    prefix = settings.MEDIA_URL_PREFIX.rstrip("/") + "/"
    if not url or not url.startswith(prefix):
        return None
    root = Path(settings.MEDIA_ROOT).resolve()
    path = (root / url[len(prefix):]).resolve()
    return path if path.is_relative_to(root) and path != root else None


def delete_song(db: Session, song: Song) -> None:
    """Deletes the song (likes/plays cascade; rooms playing it get no current song) and removes its
    media files unless another song still uses them (seed songs share album covers)."""
    urls = [u for u in (song.audio_url, song.cover_url) if u]
    song_repo.delete(db, song)
    for url in urls:
        still_used = db.scalar(
            select(Song.id).where(or_(Song.audio_url == url, Song.cover_url == url)).limit(1)
        )
        path = _media_path(url)
        if path is not None and still_used is None:
            path.unlink(missing_ok=True)

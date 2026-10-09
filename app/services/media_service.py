"""Uploaded files under MEDIA_ROOT: extension allow-lists, size-limited storage, URL <-> path."""

import uuid
from pathlib import Path

from fastapi import UploadFile, status

from app.core.config import settings
from app.core.errors import AppError, ErrorCode
from app.services import cloud_storage

# Files are served by extension (StaticFiles), so the allow-list is what keeps an upload from
# being served as HTML/JS/SVG on the API origin.
AUDIO_EXTENSIONS = {".mp3", ".wav", ".ogg", ".oga", ".opus", ".m4a", ".aac", ".flac", ".webm"}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
_CHUNK = 1024 * 1024


def has_file(upload: UploadFile | None) -> bool:
    return upload is not None and bool(upload.filename)


def check_extension(upload: UploadFile, allowed: set[str], field: str) -> str:
    suffix = Path(upload.filename or "").suffix.lower()
    if suffix not in allowed:
        raise AppError(
            ErrorCode.UNSUPPORTED_FILE_TYPE,
            f"{field} must be one of: {', '.join(sorted(allowed))}",
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            {"field": field, "allowed": sorted(allowed)},
        )
    return suffix


def store_file(upload: UploadFile, subdir: str, suffix: str, max_bytes: int, field: str) -> Path:
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


def store(upload: UploadFile, subdir: str, suffix: str, max_bytes: int, field: str) -> str:
    """Stores an upload (size-checked) and returns its public URL: a Cloudinary URL when
    CLOUDINARY_URL is set, otherwise a `/media/...` URL served from MEDIA_ROOT."""
    path = store_file(upload, subdir, suffix, max_bytes, field)
    if not cloud_storage.enabled():
        return public_url(path, subdir)
    resource_type = "image" if suffix in IMAGE_EXTENSIONS else "video"  # Cloudinary files audio as video
    try:
        return cloud_storage.upload(path, subdir, resource_type)
    finally:
        path.unlink(missing_ok=True)


def store_image(upload: UploadFile, subdir: str, field: str) -> str:
    """Checks and stores an image (cover or avatar); returns its public URL."""
    suffix = check_extension(upload, IMAGE_EXTENSIONS, field)
    return store(upload, subdir, suffix, settings.MAX_COVER_UPLOAD_BYTES, field)


def public_url(path: Path, subdir: str) -> str:
    return f"{settings.MEDIA_URL_PREFIX}/{subdir}/{path.name}"


def media_path(url: str | None) -> Path | None:
    """Local file behind a `/media/...` URL, only if it resolves inside MEDIA_ROOT."""
    prefix = settings.MEDIA_URL_PREFIX.rstrip("/") + "/"
    if not url or not url.startswith(prefix):
        return None
    root = Path(settings.MEDIA_ROOT).resolve()
    path = (root / url[len(prefix):]).resolve()
    return path if path.is_relative_to(root) and path != root else None


def remove(url: str | None) -> None:
    if cloud_storage.owns(url):
        cloud_storage.delete(url)
        return
    path = media_path(url)
    if path is not None:
        path.unlink(missing_ok=True)

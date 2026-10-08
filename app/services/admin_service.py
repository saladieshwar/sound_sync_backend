from pathlib import Path

from fastapi import UploadFile
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import Song
from app.repositories import room_repo, song_repo
from app.services import media_service

# Optional text fields where a blank value means "none".
_NULLABLE_FIELDS = ("album", "music_director")


def upload_song(
    db: Session,
    *,
    title: str,
    artist: str,
    album: str | None,
    music_director: str | None,
    category: str,
    duration_seconds: int,
    audio_file: UploadFile,
    cover_file: UploadFile | None,
) -> Song:
    audio_suffix = media_service.check_extension(audio_file, media_service.AUDIO_EXTENSIONS, "audio_file")
    has_cover = media_service.has_file(cover_file)
    if has_cover:
        media_service.check_extension(cover_file, media_service.IMAGE_EXTENSIONS, "cover_file")

    stored: list[Path] = []
    try:
        audio_path = media_service.store_file(
            audio_file, "audio", audio_suffix, settings.MAX_AUDIO_UPLOAD_BYTES, "audio_file"
        )
        stored.append(audio_path)
        cover_url = media_service.store_image(cover_file, "covers", "cover_file") if has_cover else None
        if cover_url:
            stored.append(media_service.media_path(cover_url))
        return song_repo.create(
            db,
            title=title,
            artist=artist,
            album=album or None,
            music_director=music_director or None,
            category=category,
            duration_seconds=duration_seconds,
            audio_url=media_service.public_url(audio_path, "audio"),
            cover_url=cover_url,
        )
    except BaseException:
        for path in stored:
            path.unlink(missing_ok=True)
        raise


def update_song(db: Session, song: Song, changes: dict) -> Song:
    for name, value in changes.items():
        setattr(song, name, (value or None) if name in _NULLABLE_FIELDS else value)
    return song_repo.save(db, song)


def _replace_cover(db: Session, song: Song, new_url: str | None) -> Song:
    """The old cover file is deleted once no song uses it any more (seed songs share album covers)."""
    old_url = song.cover_url
    try:
        song.cover_url = new_url
        song = song_repo.save(db, song)
    except BaseException:
        media_service.remove(new_url)
        raise
    if old_url and old_url != new_url and not song_repo.url_in_use(db, old_url):
        media_service.remove(old_url)
    return song


def set_cover(db: Session, song: Song, cover_file: UploadFile) -> Song:
    return _replace_cover(db, song, media_service.store_image(cover_file, "covers", "cover_file"))


def remove_cover(db: Session, song: Song) -> Song:
    return _replace_cover(db, song, None)


def delete_song(db: Session, song: Song) -> list[str]:
    """Deletes the song (likes/plays cascade) and removes its media files unless another song still
    uses them (seed songs share album covers). Active rooms playing it are stopped with no current
    song in the same transaction; returns their IDs so RT can tell the connected clients."""
    urls = [u for u in (song.audio_url, song.cover_url) if u]
    stopped_rooms = room_repo.stop_rooms_playing(db, song.id)
    song_repo.delete(db, song)
    for url in urls:
        if not song_repo.url_in_use(db, url):
            media_service.remove(url)
    return stopped_rooms

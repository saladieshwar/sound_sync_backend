from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import LikedSong, RecentlyPlayed
from app.repositories import library_repo
from app.services.song_service import get_song_or_404


def like_song(db: Session, user_id: int, song_id: int) -> LikedSong:
    """Idempotent: liking an already-liked song returns the existing like."""
    get_song_or_404(db, song_id)
    existing = library_repo.get_like(db, user_id, song_id)
    if existing:
        return existing
    try:
        return library_repo.add_like(db, user_id, song_id)
    except IntegrityError:
        # A concurrent request inserted the same (user_id, song_id) first.
        db.rollback()
        return library_repo.get_like(db, user_id, song_id)


def unlike_song(db: Session, user_id: int, song_id: int) -> None:
    """Idempotent: unliking a song that is not liked is a no-op."""
    like = library_repo.get_like(db, user_id, song_id)
    if like:
        library_repo.remove_like(db, like)


def log_play(db: Session, user_id: int, song_id: int) -> RecentlyPlayed:
    get_song_or_404(db, song_id)
    return library_repo.add_recently_played(db, user_id, song_id)

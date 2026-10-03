from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.models import LikedSong, RecentlyPlayed


def list_liked(db: Session, user_id: int) -> list[LikedSong]:
    stmt = (
        select(LikedSong)
        .where(LikedSong.user_id == user_id)
        .order_by(LikedSong.liked_at.desc(), LikedSong.song_id.desc())
    )
    return list(db.scalars(stmt))


def get_like(db: Session, user_id: int, song_id: int) -> LikedSong | None:
    return db.get(LikedSong, (user_id, song_id))


def add_like(db: Session, user_id: int, song_id: int) -> LikedSong:
    like = LikedSong(user_id=user_id, song_id=song_id)
    db.add(like)
    db.commit()
    db.refresh(like)
    return like


def remove_like(db: Session, like: LikedSong) -> None:
    db.delete(like)
    db.commit()


def recently_played_query(user_id: int, *, limit: int = 20) -> Select:
    """Served by ix_recently_played_user_played_at_id (user_id, played_at DESC, id DESC)."""
    return (
        select(RecentlyPlayed)
        .where(RecentlyPlayed.user_id == user_id)
        .order_by(RecentlyPlayed.played_at.desc(), RecentlyPlayed.id.desc())
        .limit(limit)
    )


def list_recently_played(db: Session, user_id: int, *, limit: int = 20) -> list[RecentlyPlayed]:
    """Play history, most recent first (a song played twice appears twice)."""
    return list(db.scalars(recently_played_query(user_id, limit=limit)))


def add_recently_played(db: Session, user_id: int, song_id: int) -> RecentlyPlayed:
    entry = RecentlyPlayed(user_id=user_id, song_id=song_id)
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry

from sqlalchemy import select
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


def list_recently_played(db: Session, user_id: int, *, limit: int = 20) -> list[RecentlyPlayed]:
    """Play history, most recent first (a song played twice appears twice)."""
    stmt = (
        select(RecentlyPlayed)
        .where(RecentlyPlayed.user_id == user_id)
        .order_by(RecentlyPlayed.played_at.desc(), RecentlyPlayed.id.desc())
        .limit(limit)
    )
    return list(db.scalars(stmt))


def add_recently_played(db: Session, user_id: int, song_id: int) -> RecentlyPlayed:
    entry = RecentlyPlayed(user_id=user_id, song_id=song_id)
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry

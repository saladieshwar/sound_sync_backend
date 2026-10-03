from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models import Song

_LIKE_ESCAPE = "\\"


def _contains_pattern(text: str) -> str:
    """ILIKE pattern matching `text` literally (user input never acts as a wildcard)."""
    escaped = (
        text.replace(_LIKE_ESCAPE, _LIKE_ESCAPE * 2)
        .replace("%", f"{_LIKE_ESCAPE}%")
        .replace("_", f"{_LIKE_ESCAPE}_")
    )
    return f"%{escaped}%"


def get_by_id(db: Session, song_id: int) -> Song | None:
    return db.get(Song, song_id)


def list_songs(db: Session, *, skip: int = 0, limit: int = 50) -> list[Song]:
    return list(db.scalars(select(Song).order_by(Song.id).offset(skip).limit(limit)))


def search(db: Session, query: str, *, limit: int = 50) -> list[Song]:
    pattern = _contains_pattern(query)
    stmt = (
        select(Song)
        .where(
            or_(
                Song.title.ilike(pattern, escape=_LIKE_ESCAPE),
                Song.artist.ilike(pattern, escape=_LIKE_ESCAPE),
                Song.album.ilike(pattern, escape=_LIKE_ESCAPE),
            )
        )
        .order_by(Song.title, Song.id)
        .limit(limit)
    )
    return list(db.scalars(stmt))


def list_by_category(db: Session, category: str, *, limit: int = 50) -> list[Song]:
    stmt = (
        select(Song)
        .where(func.lower(Song.category) == category.lower())
        .order_by(Song.title, Song.id)
        .limit(limit)
    )
    return list(db.scalars(stmt))


def list_categories(db: Session) -> list[str]:
    return list(db.scalars(select(Song.category).distinct().order_by(Song.category)))


def list_albums(db: Session) -> list[dict]:
    stmt = (
        select(
            Song.album,
            func.min(Song.artist).label("artist"),
            func.min(Song.cover_url).label("cover_url"),
            func.count(Song.id).label("song_count"),
        )
        .where(Song.album.is_not(None))
        .group_by(Song.album)
        .order_by(Song.album)
    )
    return [
        {"name": r.album, "artist": r.artist, "cover_url": r.cover_url, "song_count": r.song_count}
        for r in db.execute(stmt)
    ]


def list_by_album(db: Session, album: str) -> list[Song]:
    return list(db.scalars(select(Song).where(Song.album == album).order_by(Song.id)))


def create(db: Session, **fields) -> Song:
    song = Song(**fields)
    db.add(song)
    db.commit()
    db.refresh(song)
    return song


def delete(db: Session, song: Song) -> None:
    db.delete(song)
    db.commit()

from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import DbSession
from app.repositories import song_repo
from app.schemas.common import ErrorResponse
from app.schemas.song import AlbumOut, SongOut
from app.services import song_service

# Catalog reads are public; per-user library routes (library.py) require a JWT.
router = APIRouter(prefix="/songs", tags=["songs"])

SearchQuery = Annotated[
    str,
    Query(
        min_length=1,
        max_length=100,
        pattern=r"\S",
        description="Matches title, artist, or album (case-insensitive substring)",
    ),
]


@router.get("", response_model=list[SongOut])
def list_songs(
    db: DbSession,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
):
    return song_repo.list_songs(db, skip=skip, limit=limit)


@router.get("/search", response_model=list[SongOut])
def search_songs(db: DbSession, q: SearchQuery):
    return song_repo.search(db, q.strip())


@router.get("/categories", response_model=list[str])
def list_categories(db: DbSession):
    return song_repo.list_categories(db)


@router.get("/category/{name}", response_model=list[SongOut])
def songs_by_category(name: str, db: DbSession):
    return song_repo.list_by_category(db, name)


@router.get("/albums", response_model=list[AlbumOut])
def list_albums(db: DbSession):
    return song_repo.list_albums(db)


@router.get("/album/{name}", response_model=list[SongOut])
def songs_by_album(name: str, db: DbSession):
    return song_repo.list_by_album(db, name)


@router.get("/{song_id}", response_model=SongOut, responses={404: {"model": ErrorResponse}})
def get_song(song_id: int, db: DbSession):
    return song_service.get_song_or_404(db, song_id)

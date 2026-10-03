from fastapi import APIRouter, Query, status

from app.api.deps import CurrentUser, DbSession
from app.repositories import library_repo
from app.schemas.library import LikedSongOut, RecentlyPlayedOut
from app.services import library_service

router = APIRouter(prefix="/users/me", tags=["library"])


@router.get("/liked-songs", response_model=list[LikedSongOut])
def list_liked_songs(user: CurrentUser, db: DbSession):
    return library_repo.list_liked(db, user.id)


@router.post(
    "/liked-songs/{song_id}", response_model=LikedSongOut, status_code=status.HTTP_201_CREATED
)
def like_song(song_id: int, user: CurrentUser, db: DbSession):
    return library_service.like_song(db, user.id, song_id)


@router.delete("/liked-songs/{song_id}", status_code=status.HTTP_204_NO_CONTENT)
def unlike_song(song_id: int, user: CurrentUser, db: DbSession):
    library_service.unlike_song(db, user.id, song_id)


@router.get("/recently-played", response_model=list[RecentlyPlayedOut])
def get_recently_played(user: CurrentUser, db: DbSession, limit: int = Query(20, le=100)):
    return library_repo.list_recently_played(db, user.id, limit=limit)


@router.post(
    "/recently-played/{song_id}",
    response_model=RecentlyPlayedOut,
    status_code=status.HTTP_201_CREATED,
)
def log_play(song_id: int, user: CurrentUser, db: DbSession):
    return library_service.log_play(db, user.id, song_id)

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, File, Form, Query, UploadFile, status
from pydantic import StringConstraints

from app.api.deps import AdminUser, DbSession
from app.realtime import sync_facade
from app.repositories import room_repo, user_repo
from app.schemas.common import ErrorResponse
from app.schemas.room import RoomOut
from app.schemas.song import SongOut
from app.schemas.user import UserOut
from app.services import admin_service, room_service, song_service

router = APIRouter(
    prefix="/admin",
    tags=["admin"],
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
)

Text200 = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
OptionalText200 = Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)]
Category = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50)]


@router.post(
    "/songs",
    response_model=SongOut,
    status_code=status.HTTP_201_CREATED,
    responses={413: {"model": ErrorResponse}, 415: {"model": ErrorResponse}},
)
def upload_song(
    _: AdminUser,
    db: DbSession,
    title: Annotated[Text200, Form()],
    artist: Annotated[Text200, Form()],
    category: Annotated[Category, Form()],
    duration_seconds: Annotated[int, Form(ge=0, le=24 * 60 * 60)],
    audio_file: Annotated[UploadFile, File()],
    album: Annotated[OptionalText200 | None, Form()] = None,
    cover_file: Annotated[UploadFile | None, File()] = None,
):
    return admin_service.upload_song(
        db,
        title=title,
        artist=artist,
        album=album,
        category=category,
        duration_seconds=duration_seconds,
        audio_file=audio_file,
        cover_file=cover_file,
    )


@router.delete(
    "/songs/{song_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={404: {"model": ErrorResponse}},
)
def delete_song(song_id: int, _: AdminUser, db: DbSession, tasks: BackgroundTasks):
    for room_id in admin_service.delete_song(db, song_service.get_song_or_404(db, song_id)):
        tasks.add_task(sync_facade.resync_playback, room_id)


@router.get("/users", response_model=list[UserOut])
def list_users(
    _: AdminUser,
    db: DbSession,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
):
    return user_repo.list_all(db, skip=skip, limit=limit)


@router.get("/rooms", response_model=list[RoomOut])
def list_rooms(_: AdminUser, db: DbSession):
    return [room_service.to_room_out(r) for r in room_repo.list_active(db)]

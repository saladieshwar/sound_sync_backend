from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, File, Form, Query, UploadFile, status

from app.api.deps import AdminUser, DbSession
from app.realtime import sync_facade
from app.repositories import room_repo, user_repo
from app.schemas.common import ErrorResponse
from app.schemas.room import RoomOut
from app.schemas.song import MAX_DURATION_SECONDS, Category, OptionalText200, SongOut, SongUpdate, Text200
from app.schemas.user import UserOut
from app.services import admin_service, room_service, song_service

router = APIRouter(
    prefix="/admin",
    tags=["admin"],
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
)


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
    duration_seconds: Annotated[int, Form(ge=0, le=MAX_DURATION_SECONDS)],
    audio_file: Annotated[UploadFile, File()],
    album: Annotated[OptionalText200 | None, Form()] = None,
    music_director: Annotated[OptionalText200 | None, Form()] = None,
    cover_file: Annotated[UploadFile | None, File()] = None,
):
    return admin_service.upload_song(
        db,
        title=title,
        artist=artist,
        album=album,
        music_director=music_director,
        category=category,
        duration_seconds=duration_seconds,
        audio_file=audio_file,
        cover_file=cover_file,
    )


@router.patch(
    "/songs/{song_id}",
    response_model=SongOut,
    responses={404: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
)
def update_song(song_id: int, body: SongUpdate, _: AdminUser, db: DbSession):
    song = song_service.get_song_or_404(db, song_id)
    return admin_service.update_song(db, song, body.changes())


@router.put(
    "/songs/{song_id}/cover",
    response_model=SongOut,
    responses={
        404: {"model": ErrorResponse},
        413: {"model": ErrorResponse},
        415: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
    },
)
def set_song_cover(song_id: int, _: AdminUser, db: DbSession, cover_file: Annotated[UploadFile, File()]):
    song = song_service.get_song_or_404(db, song_id)
    return admin_service.set_cover(db, song, cover_file)


@router.delete("/songs/{song_id}/cover", response_model=SongOut, responses={404: {"model": ErrorResponse}})
def remove_song_cover(song_id: int, _: AdminUser, db: DbSession):
    return admin_service.remove_cover(db, song_service.get_song_or_404(db, song_id))


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

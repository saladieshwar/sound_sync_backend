from fastapi import APIRouter, File, Form, Query, UploadFile, status

from app.api.deps import AdminUser, DbSession
from app.repositories import room_repo, song_repo, user_repo
from app.schemas.room import RoomOut
from app.schemas.song import SongOut
from app.schemas.user import UserOut
from app.services import admin_service, room_service, song_service

router = APIRouter(prefix="/admin", tags=["admin"])


@router.post("/songs", response_model=SongOut, status_code=status.HTTP_201_CREATED)
def upload_song(
    _: AdminUser,
    db: DbSession,
    title: str = Form(...),
    artist: str = Form(...),
    category: str = Form(...),
    duration_seconds: int = Form(..., ge=0),
    album: str | None = Form(None),
    audio_file: UploadFile = File(...),
    cover_file: UploadFile | None = File(None),
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


@router.delete("/songs/{song_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_song(song_id: int, _: AdminUser, db: DbSession):
    song_repo.delete(db, song_service.get_song_or_404(db, song_id))


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

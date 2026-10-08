from typing import Annotated

from fastapi import APIRouter, File, UploadFile

from app.api.deps import CurrentUser, DbSession
from app.schemas.common import ErrorResponse
from app.schemas.user import ProfileUpdate, UserOut
from app.services import profile_service

router = APIRouter(
    prefix="/users/me",
    tags=["profile"],
    responses={401: {"model": ErrorResponse}},
)


@router.patch("", response_model=UserOut, responses={422: {"model": ErrorResponse}})
def update_profile(body: ProfileUpdate, user: CurrentUser, db: DbSession):
    return profile_service.update_profile(db, user, body)


@router.put(
    "/avatar",
    response_model=UserOut,
    responses={413: {"model": ErrorResponse}, 415: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
)
def set_avatar(user: CurrentUser, db: DbSession, avatar_file: Annotated[UploadFile, File()]):
    return profile_service.set_avatar(db, user, avatar_file)


@router.delete("/avatar", response_model=UserOut)
def remove_avatar(user: CurrentUser, db: DbSession):
    return profile_service.remove_avatar(db, user)

from fastapi import UploadFile
from sqlalchemy.orm import Session

from app.models import User
from app.repositories import user_repo
from app.schemas.user import ProfileUpdate
from app.services import media_service

AVATAR_DIR = "avatars"


def update_profile(db: Session, user: User, changes: ProfileUpdate) -> User:
    for name in changes.model_fields_set:
        value = getattr(changes, name)
        setattr(user, name, value if name == "username" else (value or None))
    return user_repo.save(db, user)


def set_avatar(db: Session, user: User, avatar_file: UploadFile) -> User:
    """Stores the new picture first, so a rejected upload leaves the old one untouched."""
    new_url = media_service.store_image(avatar_file, AVATAR_DIR, "avatar_file")
    old_url = user.avatar_url
    try:
        user.avatar_url = new_url
        user = user_repo.save(db, user)
    except BaseException:
        media_service.remove(new_url)
        raise
    media_service.remove(old_url)
    return user


def remove_avatar(db: Session, user: User) -> User:
    old_url = user.avatar_url
    user.avatar_url = None
    user = user_repo.save(db, user)
    media_service.remove(old_url)
    return user

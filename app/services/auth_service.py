from fastapi import status
from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.core.security import create_access_token, hash_password, verify_password
from app.models import User
from app.repositories import user_repo


def register(db: Session, *, username: str, email: str, password: str) -> User:
    if user_repo.get_by_email(db, email):
        raise AppError(
            ErrorCode.EMAIL_ALREADY_REGISTERED,
            "An account with this email already exists",
            status.HTTP_409_CONFLICT,
        )
    return user_repo.create(
        db, username=username, email=email, password_hash=hash_password(password)
    )


def login(db: Session, *, email: str, password: str) -> tuple[str, User]:
    user = user_repo.get_by_email(db, email)
    if not user or not verify_password(password, user.password_hash):
        raise AppError(
            ErrorCode.INVALID_CREDENTIALS,
            "Invalid email or password",
            status.HTTP_401_UNAUTHORIZED,
        )
    token = create_access_token(user.id, {"is_admin": user.is_admin})
    return token, user

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import User


def get_by_id(db: Session, user_id: int) -> User | None:
    return db.get(User, user_id)


def get_by_email(db: Session, email: str) -> User | None:
    return db.scalar(select(User).where(User.email == email.lower()))


def create(db: Session, *, username: str, email: str, password_hash: str) -> User:
    user = User(username=username, email=email.lower(), password_hash=password_hash)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def save(db: Session, user: User) -> User:
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def list_all(db: Session, *, skip: int = 0, limit: int = 100) -> list[User]:
    return list(db.scalars(select(User).order_by(User.id).offset(skip).limit(limit)))

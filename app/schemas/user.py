from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    email: EmailStr
    is_admin: bool
    created_at: datetime


class UserPublic(BaseModel):
    """Minimal user info safe to show to other room participants."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str

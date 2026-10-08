import re
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, EmailStr, StringConstraints, field_validator, model_validator

PHONE_PATTERN = re.compile(r"^\+?[0-9 ()-]+$")
PHONE_MIN_DIGITS = 7
PHONE_MAX_DIGITS = 15


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    email: EmailStr
    is_admin: bool
    full_name: str | None = None
    phone: str | None = None
    bio: str | None = None
    avatar_url: str | None = None
    created_at: datetime


class UserPublic(BaseModel):
    """Minimal user info safe to show to other room participants."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str


class ProfileUpdate(BaseModel):
    """Only the fields sent are changed. A blank full name, phone or bio clears it."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {"username": "riya", "full_name": "Riya Sharma", "phone": "+91 98765 43210", "bio": "Melody fan"}
            ]
        },
    )

    username: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=50)] | None = None
    full_name: Annotated[str, StringConstraints(strip_whitespace=True, max_length=100)] | None = None
    phone: Annotated[str, StringConstraints(strip_whitespace=True, max_length=20)] | None = None
    bio: Annotated[str, StringConstraints(strip_whitespace=True, max_length=300)] | None = None

    @field_validator("phone")
    @classmethod
    def _check_phone(cls, phone: str | None) -> str | None:
        if not phone:
            return phone
        digits = sum(c.isdigit() for c in phone)
        if not PHONE_PATTERN.match(phone) or not PHONE_MIN_DIGITS <= digits <= PHONE_MAX_DIGITS:
            raise ValueError(
                f"Phone must have {PHONE_MIN_DIGITS}-{PHONE_MAX_DIGITS} digits and only use + ( ) - and spaces"
            )
        return phone

    @model_validator(mode="after")
    def _username_cannot_be_cleared(self) -> "ProfileUpdate":
        if "username" in self.model_fields_set and self.username is None:
            raise ValueError("username cannot be empty")
        return self

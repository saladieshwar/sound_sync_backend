from typing import Annotated

from pydantic import BaseModel, ConfigDict, EmailStr, Field, StringConstraints, field_validator

from app.schemas.user import UserOut

# bcrypt only accepts passwords up to 72 bytes (bcrypt>=5 raises beyond that)
BCRYPT_MAX_BYTES = 72


def _check_password_bytes(password: str) -> str:
    if len(password.encode("utf-8")) > BCRYPT_MAX_BYTES:
        raise ValueError(f"Password must be at most {BCRYPT_MAX_BYTES} bytes")
    return password


class RegisterRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {"username": "alice", "email": "alice@soundsync.dev", "password": "alice12345"}
            ]
        }
    )

    username: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=50)]
    email: EmailStr
    password: str = Field(min_length=8, max_length=BCRYPT_MAX_BYTES)

    _password_bytes = field_validator("password")(_check_password_bytes)


class LoginRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [{"email": "admin@soundsync.dev", "password": "admin12345"}]
        }
    )

    email: EmailStr
    password: str = Field(min_length=1, max_length=BCRYPT_MAX_BYTES)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints

from app.models.room import RoomStatus
from app.schemas.user import UserPublic


class RoomCreateRequest(BaseModel):
    model_config = ConfigDict(json_schema_extra={"examples": [{"name": "Friday night"}]})

    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]


class TransferAccessRequest(BaseModel):
    target_user_id: int


class ParticipantOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user: UserPublic
    joined_at: datetime


class RoomOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    admin_user_id: int
    controller_user_id: int | None
    current_song_id: int | None
    is_playing: bool
    position_seconds: float
    state_updated_at: datetime
    status: RoomStatus
    created_at: datetime
    participants: list[ParticipantOut]
    join_link: str = ""

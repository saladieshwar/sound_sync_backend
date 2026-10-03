from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.room import RoomStatus
from app.schemas.user import UserPublic


class RoomCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)


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

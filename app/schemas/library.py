from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.schemas.song import SongOut


class LikedSongOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    song: SongOut
    liked_at: datetime


class RecentlyPlayedOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    song: SongOut
    played_at: datetime

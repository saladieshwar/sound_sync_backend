from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class SongBase(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    artist: str = Field(min_length=1, max_length=200)
    album: str | None = None
    category: str = Field(min_length=1, max_length=50)
    duration_seconds: int = Field(ge=0)


class SongOut(SongBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    audio_url: str
    cover_url: str | None
    created_at: datetime


class AlbumOut(BaseModel):
    name: str
    artist: str
    cover_url: str | None
    song_count: int

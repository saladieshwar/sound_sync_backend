from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

Text200 = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
OptionalText200 = Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)]
Category = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50)]
MAX_DURATION_SECONDS = 24 * 60 * 60


class SongBase(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    artist: str = Field(min_length=1, max_length=200)
    album: str | None = None
    music_director: str | None = None
    category: str = Field(min_length=1, max_length=50)
    duration_seconds: int = Field(ge=0)


class SongOut(SongBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    audio_url: str
    cover_url: str | None
    created_at: datetime


class SongUpdate(BaseModel):
    """Only the fields sent are changed. A blank album or music director clears it."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={"examples": [{"title": "Evening Breeze", "music_director": "A. R. Rahman"}]},
    )

    title: Text200 | None = None
    artist: Text200 | None = None
    album: OptionalText200 | None = None
    music_director: OptionalText200 | None = None
    category: Category | None = None
    duration_seconds: int | None = Field(default=None, ge=0, le=MAX_DURATION_SECONDS)

    @model_validator(mode="after")
    def _required_fields_cannot_be_cleared(self) -> "SongUpdate":
        for name in ("title", "artist", "category", "duration_seconds"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be empty")
        return self

    def changes(self) -> dict:
        return {name: getattr(self, name) for name in self.model_fields_set}


class AlbumOut(BaseModel):
    name: str
    artist: str
    cover_url: str | None
    song_count: int

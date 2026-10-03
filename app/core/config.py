from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_PLACEHOLDER_SECRETS = {"change-me", "change-me-to-a-long-random-string"}
_MIN_SECRET_LENGTH = 32


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    APP_NAME: str = "SoundSync API"
    ENVIRONMENT: str = "development"

    DATABASE_URL: str = "postgresql+psycopg://soundsync:soundsync@localhost:5432/soundsync"

    JWT_SECRET_KEY: str = "change-me"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60

    CORS_ORIGINS: str = "http://localhost:5173"
    FRONTEND_BASE_URL: str = "http://localhost:5173"

    MEDIA_ROOT: str = "./media"
    MEDIA_URL_PREFIX: str = "/media"

    @model_validator(mode="after")
    def _require_strong_secret_outside_dev(self) -> "Settings":
        weak = (
            self.JWT_SECRET_KEY in _PLACEHOLDER_SECRETS
            or len(self.JWT_SECRET_KEY) < _MIN_SECRET_LENGTH
        )
        if self.ENVIRONMENT != "development" and weak:
            raise ValueError(
                f"JWT_SECRET_KEY must be a non-placeholder value of at least "
                f"{_MIN_SECRET_LENGTH} characters when ENVIRONMENT={self.ENVIRONMENT}"
            )
        return self

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

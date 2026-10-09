from functools import lru_cache

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_PLACEHOLDER_SECRETS = {"change-me", "change-me-to-a-long-random-string"}
_MIN_SECRET_LENGTH = 32
_DEV_LAN_ORIGIN_REGEX = (
    r"^http://(localhost|127\.0\.0\.1|10(\.\d{1,3}){3}|192\.168(\.\d{1,3}){2}"
    r"|172\.(1[6-9]|2\d|3[01])(\.\d{1,3}){2}):5173$"
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    APP_NAME: str = "SoundSync API"
    ENVIRONMENT: str = "development"

    DATABASE_URL: str = "postgresql+psycopg://soundsync:soundsync@localhost:5432/soundsync"

    JWT_SECRET_KEY: str = "change-me"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60

    CORS_ORIGINS: str = "http://localhost:5173"
    # Extra allowed origins as a regex. Empty in development means "private LAN on port 5173"
    # so a second device (phone/laptop on the same Wi-Fi) can use the app for room testing.
    CORS_ORIGIN_REGEX: str = ""
    FRONTEND_BASE_URL: str = "http://localhost:5173"

    MEDIA_ROOT: str = "./media"
    MEDIA_URL_PREFIX: str = "/media"
    MAX_AUDIO_UPLOAD_BYTES: int = 50 * 1024 * 1024
    MAX_COVER_UPLOAD_BYTES: int = 5 * 1024 * 1024
    # cloudinary://<api_key>:<api_secret>@<cloud_name>. When set, uploads are stored on Cloudinary
    # instead of MEDIA_ROOT (hosts like Render's free plan wipe the local disk on every restart).
    CLOUDINARY_URL: str = ""
    CLOUDINARY_FOLDER: str = "soundsync"
    # Where uploads go without Cloudinary: "local" (MEDIA_ROOT) or "database" (media_files table).
    # Empty means "database" in production, whose host disk may be wiped, and "local" otherwise.
    MEDIA_STORAGE: str = ""

    @field_validator("DATABASE_URL")
    @classmethod
    def _use_psycopg_driver(cls, url: str) -> str:
        # Hosts such as Render hand out postgres:// or postgresql:// URLs; only psycopg 3 is installed.
        for prefix in ("postgres://", "postgresql://"):
            if url.startswith(prefix):
                return "postgresql+psycopg://" + url[len(prefix) :]
        return url

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

    @field_validator("MEDIA_STORAGE")
    @classmethod
    def _known_media_storage(cls, value: str) -> str:
        value = value.strip().lower()
        if value not in ("", "local", "database"):
            raise ValueError('MEDIA_STORAGE must be "local", "database" or empty')
        return value

    @property
    def media_in_database(self) -> bool:
        return (self.MEDIA_STORAGE or ("database" if self.ENVIRONMENT == "production" else "local")) == "database"

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @property
    def cors_origin_regex(self) -> str | None:
        if self.CORS_ORIGIN_REGEX:
            return self.CORS_ORIGIN_REGEX
        if self.ENVIRONMENT == "development":
            return _DEV_LAN_ORIGIN_REGEX
        return None


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


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

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

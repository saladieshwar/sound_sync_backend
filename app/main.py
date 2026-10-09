from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.api.routes import media
from app.core import log_redaction
from app.core.config import settings
from app.core.errors import register_exception_handlers


def create_app() -> FastAPI:
    log_redaction.install()
    app = FastAPI(title=settings.APP_NAME, version="1.0.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_origin_regex=settings.cors_origin_regex,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_exception_handlers(app)
    app.include_router(api_router)

    Path(settings.MEDIA_ROOT).mkdir(parents=True, exist_ok=True)
    app.include_router(media.router, prefix=settings.MEDIA_URL_PREFIX.rstrip("/"), tags=["media"])

    return app


app = create_app()

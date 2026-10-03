"""Structured error catalogue. Every API error is returned as:

    {"error": {"code": "<ERROR_CODE>", "message": "<human readable>", "details": {...}}}
"""

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


class ErrorCode:
    VALIDATION_ERROR = "VALIDATION_ERROR"
    EMAIL_ALREADY_REGISTERED = "EMAIL_ALREADY_REGISTERED"
    INVALID_CREDENTIALS = "INVALID_CREDENTIALS"
    INVALID_TOKEN = "INVALID_TOKEN"
    FORBIDDEN = "FORBIDDEN"
    ADMIN_REQUIRED = "ADMIN_REQUIRED"
    SONG_NOT_FOUND = "SONG_NOT_FOUND"
    ROOM_NOT_FOUND = "ROOM_NOT_FOUND"
    ROOM_CLOSED = "ROOM_CLOSED"
    NOT_ROOM_PARTICIPANT = "NOT_ROOM_PARTICIPANT"
    NOT_ROOM_CONTROLLER = "NOT_ROOM_CONTROLLER"
    USER_NOT_FOUND = "USER_NOT_FOUND"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class AppError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = status.HTTP_400_BAD_REQUEST,
        details: dict | None = None,
    ):
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}
        super().__init__(message)


def _error_body(code: str, message: str, details: dict | None = None) -> dict:
    return {"error": {"code": code, "message": message, "details": details or {}}}


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def app_error_handler(_: Request, exc: AppError):
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_body(exc.code, exc.message, exc.details),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(_: Request, exc: RequestValidationError):
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=_error_body(
                ErrorCode.VALIDATION_ERROR,
                "Request validation failed",
                {"errors": exc.errors()},
            ),
        )

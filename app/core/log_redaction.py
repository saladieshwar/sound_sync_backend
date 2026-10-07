import logging
import re

_TOKEN_IN_URL = re.compile(r"(token=)[^&\s\"']+")
# uvicorn logs WebSocket handshakes on "uvicorn.error" and HTTP requests on "uvicorn.access".
_SERVER_LOGGERS = ("uvicorn.error", "uvicorn.access")


def redact(text: str) -> str:
    return _TOKEN_IN_URL.sub(r"\1[redacted]", text)


class RedactTokenFilter(logging.Filter):
    """Removes JWTs passed as `?token=` (room WebSocket URLs) from log lines."""

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        if "token=" in message:
            record.msg = redact(message)
            record.args = ()
        return True


def install() -> None:
    for name in _SERVER_LOGGERS:
        logger = logging.getLogger(name)
        if not any(isinstance(f, RedactTokenFilter) for f in logger.filters):
            logger.addFilter(RedactTokenFilter())

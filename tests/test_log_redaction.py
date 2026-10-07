import logging

import pytest

from app.core import log_redaction

TOKEN = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiI0MiJ9.c2lnbmF0dXJl"


class _Capture(logging.Handler):
    def __init__(self):
        super().__init__()
        self.lines: list[str] = []

    def emit(self, record):
        self.lines.append(record.getMessage())


@pytest.mark.parametrize(
    ("logger_name", "fmt", "args"),
    [
        (
            "uvicorn.error",
            '%s - "WebSocket %s" [accepted]',
            ("127.0.0.1:5000", f"/rooms/ABC123/ws?token={TOKEN}"),
        ),
        (
            "uvicorn.access",
            '%s - "%s %s HTTP/%s" %d',
            ("127.0.0.1:5000", "GET", f"/rooms/ABC123/ws?token={TOKEN}&x=1", "1.1", 403),
        ),
    ],
)
def test_server_logs_never_contain_the_jwt(logger_name, fmt, args):
    log_redaction.install()
    logger = logging.getLogger(logger_name)
    capture = _Capture()
    old_level = logger.level
    logger.addHandler(capture)
    logger.setLevel(logging.INFO)
    try:
        logger.info(fmt, *args)
    finally:
        logger.removeHandler(capture)
        logger.setLevel(old_level)

    assert len(capture.lines) == 1
    assert TOKEN not in capture.lines[0]
    assert "token=[redacted]" in capture.lines[0]
    assert "/rooms/ABC123/ws" in capture.lines[0]


def test_install_is_idempotent_and_runs_with_the_app():
    from app.main import create_app

    create_app()
    log_redaction.install()
    for name in ("uvicorn.error", "uvicorn.access"):
        filters = logging.getLogger(name).filters
        assert sum(isinstance(f, log_redaction.RedactTokenFilter) for f in filters) == 1


def test_redact_leaves_other_text_alone():
    assert log_redaction.redact("GET /songs/search?q=token 200") == "GET /songs/search?q=token 200"
    assert log_redaction.redact("a?token=abc&b=2") == "a?token=[redacted]&b=2"

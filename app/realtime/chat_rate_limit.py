"""In-memory per-user chat throttle for one API process (rooms already require a single worker)."""

import time
from threading import Lock

from app.realtime.events import CHAT_MIN_INTERVAL_SECONDS

_lock = Lock()
_last_sent: dict[tuple[str, int], float] = {}


def allow(room_id: str, user_id: int, *, now: float | None = None) -> bool:
    """Returns True and records the send time when the user may post; False if too soon."""
    key = (room_id, user_id)
    stamp = time.monotonic() if now is None else now
    with _lock:
        previous = _last_sent.get(key)
        if previous is not None and stamp - previous < CHAT_MIN_INTERVAL_SECONDS:
            return False
        _last_sent[key] = stamp
        return True


def clear(room_id: str | None = None) -> None:
    """Drops throttle state for one room, or everything (tests)."""
    with _lock:
        if room_id is None:
            _last_sent.clear()
            return
        for key in [k for k in _last_sent if k[0] == room_id]:
            del _last_sent[key]

"""Helpers for tests that need a real running server (WebSocket routes open their own DB sessions,
so they cannot use the rolled-back test session). Used by room sync, E2E and network tests."""

import json
import socket
import threading
import time
import uuid
from contextlib import contextmanager

import httpx
import pytest
import uvicorn
from sqlalchemy import delete
from websockets.exceptions import ConnectionClosed
from websockets.sync.client import connect as ws_connect

from app.db.session import SessionLocal
from app.main import app
from app.models import Song, User

PASSWORD = "s3cret-pass"
RECV_TIMEOUT = 5.0


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@contextmanager
def live_server():
    """Runs the app with uvicorn in a background thread; yields "host:port"."""
    port = free_port()
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=srv.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 15
    while not srv.started:
        if time.monotonic() > deadline:
            pytest.fail("live server did not start")
        time.sleep(0.05)
    try:
        yield f"127.0.0.1:{port}"
    finally:
        srv.should_exit = True
        thread.join(timeout=10)


@contextmanager
def cleanup_rows():
    """Tracks committed users/songs ({"emails": [...], "song_ids": [...]}) and deletes them after.
    Rooms, participants, likes and plays cascade from users and songs."""
    rows = {"emails": [], "song_ids": []}
    try:
        yield rows
    finally:
        with SessionLocal() as db:
            if rows["emails"]:
                db.execute(delete(User).where(User.email.in_(rows["emails"])))
            if rows["song_ids"]:
                db.execute(delete(Song).where(Song.id.in_(rows["song_ids"])))
            db.commit()


def make_songs(created: dict, count: int = 2, duration: int = 180) -> list[int]:
    with SessionLocal() as db:
        items = [
            Song(
                title=f"Sync Test {i} {uuid.uuid4().hex[:6]}",
                artist="QA",
                album="Room Sync",
                category="test",
                duration_seconds=duration,
                audio_url="/media/audio/sync-test.wav",
                cover_url=None,
            )
            for i in range(count)
        ]
        db.add_all(items)
        db.commit()
        ids = [s.id for s in items]
    created["song_ids"].extend(ids)
    return ids


class Peer:
    """A registered, logged-in user. `ws_base` lets sockets go through a different address
    (e.g. a network-conditions proxy) than REST calls."""

    def __init__(self, base: str, name: str, created: dict, ws_base: str | None = None):
        self.base = base
        self.ws_base = ws_base or base
        self.http = httpx.Client(base_url=f"http://{base}", timeout=10)
        email = f"sync_{name}_{uuid.uuid4().hex[:8]}@soundsync.dev"
        created["emails"].append(email)
        reg = self.http.post(
            "/auth/register", json={"username": name, "email": email, "password": PASSWORD}
        )
        assert reg.status_code == 201, reg.text
        self.id = reg.json()["id"]
        token = self.http.post("/auth/login", json={"email": email, "password": PASSWORD})
        self.token = token.json()["access_token"]
        self.http.headers["Authorization"] = f"Bearer {self.token}"

    def create_room(self) -> str:
        response = self.http.post("/rooms", json={"name": "Sync test"})
        assert response.status_code == 201, response.text
        return response.json()["id"]

    def join(self, room_id: str) -> None:
        assert self.http.post(f"/rooms/{room_id}/join").status_code == 200

    def leave(self, room_id: str) -> None:
        assert self.http.post(f"/rooms/{room_id}/leave").status_code == 200

    def transfer(self, room_id: str, target_id: int) -> None:
        response = self.http.post(
            f"/rooms/{room_id}/transfer-access", json={"target_user_id": target_id}
        )
        assert response.status_code == 200, response.text

    def socket(self, room_id: str, token: str | None = None):
        return ws_connect(
            f"ws://{self.ws_base}/rooms/{room_id}/ws?token={token or self.token}", open_timeout=5
        )

    @contextmanager
    def open(self, room_id: str):
        """Connected socket plus its initial room_state payload: `with peer.open(id) as (ws, state)`."""
        with self.socket(room_id) as ws:
            yield ws, expect(ws, "room_state")["payload"]


def recv(ws, timeout: float = RECV_TIMEOUT) -> dict:
    return json.loads(ws.recv(timeout=timeout))


def expect(ws, event_type: str, timeout: float = RECV_TIMEOUT) -> dict:
    """Next message of `event_type`, skipping presence noise (joins/leaves of other sockets)."""
    deadline = time.monotonic() + timeout
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            pytest.fail(f"no {event_type!r} message within {timeout}s")
        message = recv(ws, remaining)
        if message["type"] == event_type:
            return message
        if message["type"] not in ("user_joined", "user_left"):
            pytest.fail(f"expected {event_type!r}, got {message}")


def assert_closed(ws, code: int) -> None:
    with pytest.raises(ConnectionClosed):
        while True:
            ws.recv(timeout=RECV_TIMEOUT)
    assert ws.close_code == code


def assert_silent(ws, wait: float = 0.6) -> None:
    with pytest.raises(TimeoutError):
        recv(ws, wait)


def send(ws, event_type: str, **payload) -> None:
    ws.send(json.dumps({"type": event_type, "payload": payload}))

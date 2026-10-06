"""Phase 5 â€” multi-client room sync over a real WebSocket server (RT + BE + QA).

The WS route opens its own DB sessions, so these tests run a live uvicorn server in a background
thread against the configured database. Every user/song created here is deleted at teardown
(rooms and participant rows cascade from users).
"""

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
# A broadcast must reach every client well inside the drift tolerance (0.5 s).
MAX_DELIVERY_SECONDS = 0.5


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def server():
    port = _free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    srv = uvicorn.Server(config)
    thread = threading.Thread(target=srv.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 15
    while not srv.started:
        if time.monotonic() > deadline:
            pytest.fail("live server did not start")
        time.sleep(0.05)
    yield f"127.0.0.1:{port}"
    srv.should_exit = True
    thread.join(timeout=10)


@pytest.fixture(scope="module")
def created():
    """Tracks committed rows and removes them after the module."""
    rows = {"emails": [], "song_ids": []}
    yield rows
    with SessionLocal() as db:
        if rows["emails"]:
            db.execute(delete(User).where(User.email.in_(rows["emails"])))
        if rows["song_ids"]:
            db.execute(delete(Song).where(Song.id.in_(rows["song_ids"])))
        db.commit()


@pytest.fixture(scope="module")
def songs(created):
    with SessionLocal() as db:
        items = [
            Song(
                title=f"Sync Test {i} {uuid.uuid4().hex[:6]}",
                artist="QA",
                album="Room Sync",
                category="test",
                duration_seconds=180,
                audio_url="/media/audio/sync-test.wav",
                cover_url=None,
            )
            for i in range(2)
        ]
        db.add_all(items)
        db.commit()
        ids = [s.id for s in items]
    created["song_ids"].extend(ids)
    return ids


class Peer:
    def __init__(self, base: str, name: str, created: dict):
        self.base = base
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
            f"ws://{self.base}/rooms/{room_id}/ws?token={token or self.token}", open_timeout=5
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


@pytest.fixture(scope="module")
def peers(server, created):
    return {name: Peer(server, name, created) for name in ("admin", "bob", "carol")}


@pytest.fixture
def room(peers):
    """Fresh room: admin created it, bob and carol joined via REST."""
    room_id = peers["admin"].create_room()
    peers["bob"].join(room_id)
    peers["carol"].join(room_id)
    return room_id


# --- connection rules (ROOM-04) -----------------------------------------------------


def test_socket_rejected_without_rest_join(peers):
    room_id = peers["admin"].create_room()
    with peers["bob"].socket(room_id) as ws:
        assert_closed(ws, 1008)


def test_socket_rejected_with_bad_token(peers, room):
    with peers["bob"].socket(room, token="not-a-jwt") as ws:
        assert_closed(ws, 1008)


def test_socket_rejected_for_closed_room(peers, room):
    peers["admin"].leave(room)
    with peers["bob"].socket(room) as ws:
        assert_closed(ws, 1008)


def test_connect_receives_room_state_with_online_users(peers, room):
    admin, bob = peers["admin"], peers["bob"]
    with admin.open(room) as (a, state):
        assert state["id"] == room
        assert state["controller_user_id"] == admin.id
        assert state["online_user_ids"] == [admin.id]

        with bob.open(room) as (_, state_b):
            assert sorted(state_b["online_user_ids"]) == sorted([admin.id, bob.id])
            assert expect(a, "user_joined")["payload"] == {"user_id": bob.id}


def test_join_link_lowercase_room_id_connects(peers, room):
    with peers["bob"].open(room.lower()) as (_, state):
        assert state["id"] == room


# --- playback sync (ROOM-05) --------------------------------------------------------


def test_play_pause_seek_song_change_sync_across_three_clients(peers, room, songs):
    with (
        peers["admin"].open(room) as (a, _),
        peers["bob"].open(room) as (b, _),
        peers["carol"].open(room) as (c, _),
    ):
        steps = [
            ("song_change", {"position_seconds": 0, "song_id": songs[0]}, True, 0.0, songs[0]),
            ("seek", {"position_seconds": 42.5}, True, 42.5, songs[0]),
            ("pause", {"position_seconds": 43.0}, False, 43.0, songs[0]),
            ("play", {"position_seconds": 43.0}, True, 43.0, songs[0]),
            ("song_change", {"position_seconds": 0, "song_id": songs[1]}, True, 0.0, songs[1]),
        ]
        for event, payload, playing, position, song_id in steps:
            sent_at = time.time()
            send(a, event, **payload)
            for ws in (a, b, c):
                message = expect(ws, event)
                assert time.time() - sent_at < MAX_DELIVERY_SECONDS
                assert message["sender_user_id"] == peers["admin"].id
                assert message["payload"] == {
                    "song_id": song_id,
                    "position_seconds": position,
                    "is_playing": playing,
                }


def test_room_state_reflects_persisted_playback(peers, room, songs):
    with peers["admin"].open(room) as (a, _):
        send(a, "song_change", position_seconds=0, song_id=songs[0])
        expect(a, "song_change")
        send(a, "seek", position_seconds=60)
        expect(a, "seek")
    with peers["carol"].open(room) as (_, state):
        assert state["current_song_id"] == songs[0]
        assert state["position_seconds"] == 60.0
        assert state["is_playing"] is True


# --- controller validation (ROOM-06) ------------------------------------------------


def test_non_controller_events_are_rejected_and_not_broadcast(peers, room, songs):
    with peers["admin"].open(room) as (a, _), peers["bob"].open(room) as (b, _):
        expect(a, "user_joined")
        for event, payload in (
            ("play", {"position_seconds": 0}),
            ("song_change", {"position_seconds": 0, "song_id": songs[0]}),
        ):
            send(b, event, **payload)
            assert expect(b, "error")["payload"] == {"code": "NOT_ROOM_CONTROLLER"}
            assert_silent(a)


# --- control transfer (ROOM-07) -----------------------------------------------------


def test_transfer_control_both_directions(peers, room, songs):
    admin, bob = peers["admin"], peers["bob"]
    with admin.open(room) as (a, _), bob.open(room) as (b, _):
        admin.transfer(room, bob.id)
        for ws in (a, b):
            assert expect(ws, "access_transfer")["payload"] == {"controller_user_id": bob.id}

        send(b, "song_change", position_seconds=0, song_id=songs[0])
        for ws in (a, b):
            assert expect(ws, "song_change")["sender_user_id"] == bob.id
        send(a, "pause", position_seconds=1)
        assert expect(a, "error")["payload"]["code"] == "NOT_ROOM_CONTROLLER"

        bob.transfer(room, admin.id)
        for ws in (a, b):
            assert expect(ws, "access_transfer")["payload"] == {"controller_user_id": admin.id}

        send(a, "pause", position_seconds=5)
        for ws in (a, b):
            message = expect(ws, "pause")
            assert message["sender_user_id"] == admin.id
            assert message["payload"]["is_playing"] is False
        send(b, "play", position_seconds=5)
        assert expect(b, "error")["payload"]["code"] == "NOT_ROOM_CONTROLLER"


# --- leave / admin leave (ROOM-09, ROOM-10) -----------------------------------------


def test_participant_leave_closes_their_socket_and_notifies_room(peers, room):
    admin, bob = peers["admin"], peers["bob"]
    with admin.open(room) as (a, _), bob.open(room) as (b, _):
        expect(a, "user_joined")
        admin.transfer(room, bob.id)
        expect(a, "access_transfer")
        expect(b, "access_transfer")

        bob.leave(room)
        left = expect(a, "user_left")
        assert left["payload"] == {
            "user_id": bob.id,
            "reason": "left",
            "controller_user_id": admin.id,
        }
        assert_closed(b, 1000)
        assert_silent(a)


def test_admin_leave_mid_session_closes_room_for_everyone(peers, room, songs):
    with (
        peers["admin"].open(room) as (a, _),
        peers["bob"].open(room) as (b, _),
        peers["carol"].open(room) as (c, _),
    ):
        send(a, "song_change", position_seconds=0, song_id=songs[0])
        for ws in (a, b, c):
            expect(ws, "song_change")

        peers["admin"].leave(room)
        for ws in (a, b, c):
            expect(ws, "room_closed")
            assert_closed(ws, 1000)
    assert peers["bob"].http.get(f"/rooms/{room}").status_code == 410


# --- reconnect / drop (ROOM-11, RES-03) ---------------------------------------------


def test_network_drop_then_reconnect_resyncs(peers, room, songs):
    admin, bob = peers["admin"], peers["bob"]
    with admin.open(room) as (a, _):
        with bob.open(room) as (b, _):
            expect(a, "user_joined")
            send(a, "song_change", position_seconds=0, song_id=songs[0])
            expect(a, "song_change")
            expect(b, "song_change")
        dropped = expect(a, "user_left")
        assert dropped["payload"] == {"user_id": bob.id, "reason": "disconnected"}

        send(a, "seek", position_seconds=90)
        expect(a, "seek")
        send(a, "pause", position_seconds=91)
        expect(a, "pause")

        with bob.open(room) as (b2, state):
            assert expect(a, "user_joined")["payload"] == {"user_id": bob.id}
            assert state["current_song_id"] == songs[0]
            assert state["position_seconds"] == 91.0
            assert state["is_playing"] is False
            assert bob.id in [p["user"]["id"] for p in state["participants"]]

            send(a, "play", position_seconds=91)
            assert expect(b2, "play")["payload"]["is_playing"] is True


def test_second_tab_does_not_duplicate_presence(peers, room):
    bob = peers["bob"]
    with peers["admin"].open(room) as (a, _):
        with bob.open(room):
            assert expect(a, "user_joined")["payload"] == {"user_id": bob.id}
            with bob.open(room):
                assert_silent(a)
            assert_silent(a)
        assert expect(a, "user_left")["payload"]["user_id"] == bob.id


# --- resilience (ROOM-12) -----------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "code"),
    [
        ("not json", "INVALID_MESSAGE"),
        (json.dumps({"payload": {}}), "INVALID_MESSAGE"),
        (json.dumps({"type": "dance", "payload": {}}), "INVALID_MESSAGE"),
        (json.dumps({"type": "room_closed", "payload": {}}), "EVENT_NOT_ALLOWED"),
        (json.dumps({"type": "seek", "payload": {"position_seconds": -1}}), "INVALID_PAYLOAD"),
        (json.dumps({"type": "song_change", "payload": {"position_seconds": 0}}), "INVALID_PAYLOAD"),
        (json.dumps({"type": "play", "payload": {"position_seconds": 0}}), "NO_CURRENT_SONG"),
        (
            json.dumps({"type": "song_change", "payload": {"position_seconds": 0, "song_id": 0}}),
            "SONG_NOT_FOUND",
        ),
    ],
)
def test_bad_messages_get_error_and_socket_stays_up(peers, room, songs, raw, code):
    with peers["admin"].open(room) as (a, _):
        a.send(raw)
        assert expect(a, "error")["payload"] == {"code": code}

        send(a, "song_change", position_seconds=0, song_id=songs[0])
        assert expect(a, "song_change")["payload"]["song_id"] == songs[0]


def test_binary_frame_gets_error_and_socket_stays_up(peers, room, songs):
    with peers["admin"].open(room) as (a, _):
        a.send(b"\x00\x01")
        assert expect(a, "error")["payload"] == {"code": "INVALID_MESSAGE"}
        send(a, "song_change", position_seconds=0, song_id=songs[0])
        expect(a, "song_change")


"""Phase 6 - end-to-end API path across every module (BE + DATA + RT + QA).

One uninterrupted journey against a live server and the real database:
register -> login -> browse -> search -> play/like -> library -> create room -> second user joins ->
both connect over WebSocket -> controller drives playback -> transfer -> leave -> room closed.
"""

import time
import uuid

import httpx
import pytest
from sqlalchemy import update
from websockets.sync.client import connect as ws_connect

from app.db.session import SessionLocal
from app.models import Song
from tests.live import PASSWORD, assert_closed, cleanup_rows, expect, live_server, make_songs, send

MAX_DELIVERY_SECONDS = 0.5


@pytest.fixture(scope="module")
def server():
    with live_server() as base:
        yield base


@pytest.fixture(scope="module")
def created():
    with cleanup_rows() as rows:
        yield rows


def register_and_login(http: httpx.Client, created: dict, name: str) -> dict:
    email = f"e2e_{name}_{uuid.uuid4().hex[:8]}@soundsync.dev"
    created["emails"].append(email)
    reg = http.post("/auth/register", json={"username": name, "email": email, "password": PASSWORD})
    assert reg.status_code == 201, reg.text
    assert "password" not in reg.text and "password_hash" not in reg.text

    assert http.post("/auth/login", json={"email": email, "password": "wrong-pass"}).status_code == 401
    login = http.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert login.status_code == 200, login.text
    token = login.json()["access_token"]
    http.headers["Authorization"] = f"Bearer {token}"

    me = http.get("/auth/me")
    assert me.status_code == 200
    assert me.json()["id"] == reg.json()["id"]
    return {"id": me.json()["id"], "token": token}


def test_full_journey_register_browse_play_room_sync_leave(server, created):
    category = f"e2e-{uuid.uuid4().hex[:6]}"
    song_ids = make_songs(created, count=2)
    _tag_songs(song_ids, category)

    with httpx.Client(base_url=f"http://{server}", timeout=10) as alice_http, httpx.Client(
        base_url=f"http://{server}", timeout=10
    ) as bob_http:
        # --- auth ------------------------------------------------------------------------
        assert alice_http.get("/health").json() == {"status": "ok"}
        assert alice_http.get("/users/me/liked-songs").status_code == 401
        alice = register_and_login(alice_http, created, "alice")
        bob = register_and_login(bob_http, created, "bob")

        # --- browse / search (catalog) ---------------------------------------------------
        assert category in alice_http.get("/songs/categories").json()
        in_category = alice_http.get(f"/songs/category/{category.upper()}").json()
        assert sorted(s["id"] for s in in_category) == sorted(song_ids)
        song = alice_http.get(f"/songs/{song_ids[0]}").json()
        album = next(a for a in alice_http.get("/songs/albums").json() if a["name"] == song["album"])
        assert album["song_count"] >= 2
        assert song_ids[0] in [s["id"] for s in alice_http.get(f"/songs/album/{song['album']}").json()]
        found = alice_http.get("/songs/search", params={"q": song["title"][-6:].upper()}).json()
        assert [s["id"] for s in found] == [song_ids[0]]

        # --- play + library --------------------------------------------------------------
        for sid in (song_ids[0], song_ids[1], song_ids[0]):
            assert alice_http.post(f"/users/me/recently-played/{sid}").status_code == 201
        recent = alice_http.get("/users/me/recently-played").json()
        assert [r["song"]["id"] for r in recent[:2]] == [song_ids[0], song_ids[1]]
        assert alice_http.post(f"/users/me/liked-songs/{song_ids[1]}").status_code == 201
        liked = alice_http.get("/users/me/liked-songs").json()
        assert [x["song"]["id"] for x in liked] == [song_ids[1]]

        # --- create / join room ----------------------------------------------------------
        room = alice_http.post("/rooms", json={"name": "E2E party"})
        assert room.status_code == 201, room.text
        room_id = room.json()["id"]
        assert room.json()["controller_user_id"] == alice["id"]
        assert bob_http.get(f"/rooms/{room_id}").status_code == 403
        joined = bob_http.post(f"/rooms/{room_id}/join")
        assert joined.status_code == 200
        assert {p["user"]["id"] for p in joined.json()["participants"]} == {alice["id"], bob["id"]}

        # --- real-time sync --------------------------------------------------------------
        def socket(user):
            return ws_connect(f"ws://{server}/rooms/{room_id}/ws?token={user['token']}", open_timeout=5)

        with socket(alice) as a, socket(bob) as b:
            assert expect(a, "room_state")["payload"]["id"] == room_id
            state_b = expect(b, "room_state")["payload"]
            assert sorted(state_b["online_user_ids"]) == sorted([alice["id"], bob["id"]])

            for event, payload, playing, position in (
                ("song_change", {"song_id": song_ids[0], "position_seconds": 0}, True, 0.0),
                ("seek", {"position_seconds": 30}, True, 30.0),
                ("pause", {"position_seconds": 31}, False, 31.0),
                ("play", {"position_seconds": 31}, True, 31.0),
            ):
                sent = time.time()
                send(a, event, **payload)
                for ws in (a, b):
                    message = expect(ws, event)
                    assert time.time() - sent < MAX_DELIVERY_SECONDS
                    assert message["payload"] == {
                        "song_id": song_ids[0],
                        "position_seconds": position,
                        "is_playing": playing,
                    }

            persisted = bob_http.get(f"/rooms/{room_id}").json()
            assert persisted["current_song_id"] == song_ids[0]
            assert persisted["is_playing"] is True

            # Control hand-off: bob drives, alice can no longer.
            assert alice_http.post(
                f"/rooms/{room_id}/transfer-access", json={"target_user_id": bob["id"]}
            ).status_code == 200
            for ws in (a, b):
                assert expect(ws, "access_transfer")["payload"] == {"controller_user_id": bob["id"]}
            send(b, "song_change", song_id=song_ids[1], position_seconds=0)
            for ws in (a, b):
                assert expect(ws, "song_change")["sender_user_id"] == bob["id"]
            send(a, "pause", position_seconds=2)
            assert expect(a, "error")["payload"] == {"code": "NOT_ROOM_CONTROLLER"}

            # --- leave -------------------------------------------------------------------
            assert bob_http.post(f"/rooms/{room_id}/leave").json() == {"message": "Left room"}
            left = expect(a, "user_left")["payload"]
            assert left == {"user_id": bob["id"], "reason": "left", "controller_user_id": alice["id"]}
            assert_closed(b, 1000)

            assert alice_http.post(f"/rooms/{room_id}/leave").json() == {"message": "Room closed"}
            expect(a, "room_closed")
            assert_closed(a, 1000)

        assert alice_http.get(f"/rooms/{room_id}").status_code == 410
        assert bob_http.post(f"/rooms/{room_id}/join").status_code == 410

        # Library survives the room session.
        assert alice_http.get("/users/me/liked-songs").json()[0]["song"]["id"] == song_ids[1]


def _tag_songs(song_ids: list[int], category: str) -> None:
    with SessionLocal() as db:
        db.execute(
            update(Song)
            .where(Song.id.in_(song_ids))
            .values(category=category, album=f"E2E Album {category}")
        )
        db.commit()

"""Phase 5 - multi-client room sync over a real WebSocket server (RT + BE + QA).

The WS route opens its own DB sessions, so these tests run a live uvicorn server in a background
thread against the configured database. Every user/song created here is deleted at teardown
(rooms and participant rows cascade from users).
"""

import json
import threading
import time

import pytest
from sqlalchemy import update

from app.db.session import SessionLocal
from app.models import MusicalRoom, RoomStatus, User
from tests.live import Peer, assert_closed, assert_silent, cleanup_rows, expect, live_server, make_songs, send

# A broadcast must reach every client well inside the drift tolerance (0.5 s).
MAX_DELIVERY_SECONDS = 0.5


@pytest.fixture(scope="module")
def server():
    with live_server() as base:
        yield base


@pytest.fixture(scope="module")
def created():
    with cleanup_rows() as rows:
        yield rows


@pytest.fixture(scope="module")
def songs(created):
    return make_songs(created)


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


# --- ordering guarantees ------------------------------------------------------------


def test_joiner_mid_burst_sees_events_in_commit_order_with_no_gap(peers, room, songs):
    admin, bob = peers["admin"], peers["bob"]
    positions = [float(p) for p in range(1, 41)]
    with admin.open(room) as (a, _):
        send(a, "song_change", position_seconds=0, song_id=songs[0])
        expect(a, "song_change")
        send(a, "pause", position_seconds=0)
        expect(a, "pause")

        burst = threading.Thread(
            target=lambda: [send(a, "seek", position_seconds=p) for p in positions]
        )
        burst.start()
        with bob.open(room) as (b, state):
            seen = [state["position_seconds"]]
            while seen[-1] != positions[-1]:
                seen.append(expect(b, "seek")["payload"]["position_seconds"])
        burst.join()

        assert all(earlier < later for earlier, later in zip(seen, seen[1:])), seen
        assert [expect(a, "seek")["payload"]["position_seconds"] for _ in positions] == positions


# --- clock sync ---------------------------------------------------------------------


def test_time_sync_is_answered_only_to_the_sender(peers, room):
    with peers["admin"].open(room) as (a, _), peers["bob"].open(room) as (b, _):
        expect(a, "user_joined")
        before = time.time() * 1000
        send(b, "time_sync", client_ts=123456.5)
        reply = expect(b, "time_sync")
        assert reply["payload"] == {"client_ts": 123456.5}
        assert before - 1000 <= reply["server_ts"] <= time.time() * 1000 + 1000
        assert_silent(a)


def test_time_sync_without_client_ts_is_invalid(peers, room):
    with peers["admin"].open(room) as (a, _):
        send(a, "time_sync")
        assert expect(a, "error")["payload"] == {"code": "INVALID_PAYLOAD"}


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


def test_playback_after_room_closed_meanwhile_gets_room_closed_then_1008(peers, room, songs):
    with peers["admin"].open(room) as (a, _), peers["bob"].open(room) as (b, _):
        expect(a, "user_joined")
        with SessionLocal() as db:
            db.execute(
                update(MusicalRoom).where(MusicalRoom.id == room).values(status=RoomStatus.CLOSED)
            )
            db.commit()

        send(a, "play", position_seconds=0)
        assert expect(a, "error")["payload"] == {"code": "ROOM_CLOSED"}
        assert_closed(a, 1008)
        assert expect(b, "user_left")["payload"] == {"user_id": peers["admin"].id, "reason": "disconnected"}


def test_admin_deleting_the_playing_song_stops_the_room_for_everyone(peers, room, created):
    [song_id] = make_songs(created, count=1)
    site_admin = peers["carol"]
    with SessionLocal() as db:
        db.execute(update(User).where(User.id == site_admin.id).values(is_admin=True))
        db.commit()
    try:
        with peers["admin"].open(room) as (a, _), peers["bob"].open(room) as (b, _):
            expect(a, "user_joined")
            send(a, "song_change", position_seconds=5, song_id=song_id)
            for ws in (a, b):
                expect(ws, "song_change")

            assert site_admin.http.delete(f"/admin/songs/{song_id}").status_code == 204
            stopped = {"song_id": None, "position_seconds": 0.0, "is_playing": False}
            for ws in (a, b):
                assert expect(ws, "pause")["payload"] == stopped
            state = peers["bob"].http.get(f"/rooms/{room}").json()
            assert (state["current_song_id"], state["is_playing"], state["position_seconds"]) == (None, False, 0.0)

            send(a, "play", position_seconds=0)
            assert expect(a, "error")["payload"] == {"code": "NO_CURRENT_SONG"}
    finally:
        with SessionLocal() as db:
            db.execute(update(User).where(User.id == site_admin.id).values(is_admin=False))
            db.commit()


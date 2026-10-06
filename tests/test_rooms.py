"""Phase 5 — Musical Room REST API (BE) and room tables (DATA)."""

import re

import pytest

from app.core.config import settings
from app.core.errors import AppError
from app.models import MusicalRoom, RoomParticipant, RoomStatus
from app.services import room_service


@pytest.fixture
def users(client, login_headers):
    """Three logged-in users: admin, bob, carol -> (headers, user_id)."""

    def _user(name):
        headers = login_headers(username=name)
        return headers, client.get("/auth/me", headers=headers).json()["id"]

    return {name: _user(name) for name in ("admin", "bob", "carol")}


def _create(client, headers, name="Friday night"):
    response = client.post("/rooms", json={"name": name}, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


def _participant_ids(room):
    return sorted(p["user"]["id"] for p in room["participants"])


# --- create -------------------------------------------------------------------------


def test_create_room_makes_creator_admin_controller_and_participant(client, users):
    headers, admin_id = users["admin"]
    room = _create(client, headers, "  Friday night  ")

    assert re.fullmatch(r"[A-Z0-9]{8}", room["id"])
    assert room["name"] == "Friday night"
    assert room["admin_user_id"] == admin_id
    assert room["controller_user_id"] == admin_id
    assert room["status"] == "active"
    assert room["is_playing"] is False
    assert room["current_song_id"] is None
    assert _participant_ids(room) == [admin_id]


def test_create_room_returns_shareable_join_link(client, users):
    room = _create(client, users["admin"][0])
    assert room["join_link"] == f"{settings.FRONTEND_BASE_URL.rstrip('/')}/room/{room['id']}"


def test_room_ids_are_unique(client, users):
    ids = {_create(client, users["admin"][0])["id"] for _ in range(5)}
    assert len(ids) == 5


@pytest.mark.parametrize("name", ["", "   ", "x" * 101])
def test_create_room_rejects_invalid_name(client, users, name):
    response = client.post("/rooms", json={"name": name}, headers=users["admin"][0])
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_room_endpoints_require_auth(client, users):
    room = _create(client, users["admin"][0])
    assert client.post("/rooms", json={"name": "x"}).status_code == 401
    assert client.get(f"/rooms/{room['id']}").status_code == 401
    assert client.post(f"/rooms/{room['id']}/join").status_code == 401
    assert client.post(f"/rooms/{room['id']}/leave").status_code == 401
    assert (
        client.post(f"/rooms/{room['id']}/transfer-access", json={"target_user_id": 1}).status_code
        == 401
    )


# --- get / join ---------------------------------------------------------------------


def test_get_room_is_for_participants_only(client, users):
    room = _create(client, users["admin"][0])
    outsider = client.get(f"/rooms/{room['id']}", headers=users["bob"][0])
    assert outsider.status_code == 403
    assert outsider.json()["error"]["code"] == "NOT_ROOM_PARTICIPANT"

    client.post(f"/rooms/{room['id']}/join", headers=users["bob"][0])
    assert client.get(f"/rooms/{room['id']}", headers=users["bob"][0]).status_code == 200


def test_join_by_room_id_adds_participant(client, users):
    room = _create(client, users["admin"][0])
    bob_headers, bob_id = users["bob"]

    joined = client.post(f"/rooms/{room['id']}/join", headers=bob_headers)
    assert joined.status_code == 200
    assert bob_id in _participant_ids(joined.json())
    assert joined.json()["controller_user_id"] == users["admin"][1]


def test_join_is_case_insensitive_like_a_typed_room_id(client, users):
    room = _create(client, users["admin"][0])
    joined = client.post(f"/rooms/{room['id'].lower()}/join", headers=users["bob"][0])
    assert joined.status_code == 200
    assert joined.json()["id"] == room["id"]


def test_join_is_idempotent(client, users):
    room = _create(client, users["admin"][0])
    client.post(f"/rooms/{room['id']}/join", headers=users["bob"][0])
    again = client.post(f"/rooms/{room['id']}/join", headers=users["bob"][0])
    assert again.status_code == 200
    assert _participant_ids(again.json()) == sorted([users["admin"][1], users["bob"][1]])


def test_join_unknown_room_is_404(client, users):
    response = client.post("/rooms/NOPE0000/join", headers=users["bob"][0])
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "ROOM_NOT_FOUND"


def test_join_closed_room_is_410(client, users):
    room = _create(client, users["admin"][0])
    client.post(f"/rooms/{room['id']}/leave", headers=users["admin"][0])
    response = client.post(f"/rooms/{room['id']}/join", headers=users["bob"][0])
    assert response.status_code == 410
    assert response.json()["error"]["code"] == "ROOM_CLOSED"


# --- leave (DATA: cascade + admin-leave rule) ---------------------------------------


def test_leave_removes_participant_row(client, db, users):
    room = _create(client, users["admin"][0])
    bob_headers, bob_id = users["bob"]
    client.post(f"/rooms/{room['id']}/join", headers=bob_headers)

    response = client.post(f"/rooms/{room['id']}/leave", headers=bob_headers)
    assert response.status_code == 200
    assert response.json() == {"message": "Left room"}
    assert db.get(RoomParticipant, (room["id"], bob_id)) is None
    assert db.get(MusicalRoom, room["id"]).status == RoomStatus.ACTIVE
    assert client.get(f"/rooms/{room['id']}", headers=bob_headers).status_code == 403


def test_leave_when_not_participant_is_403(client, users):
    room = _create(client, users["admin"][0])
    response = client.post(f"/rooms/{room['id']}/leave", headers=users["bob"][0])
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "NOT_ROOM_PARTICIPANT"


def test_controller_leaving_returns_control_to_admin(client, db, users):
    room = _create(client, users["admin"][0])
    bob_headers, bob_id = users["bob"]
    client.post(f"/rooms/{room['id']}/join", headers=bob_headers)
    client.post(
        f"/rooms/{room['id']}/transfer-access",
        json={"target_user_id": bob_id},
        headers=users["admin"][0],
    )

    client.post(f"/rooms/{room['id']}/leave", headers=bob_headers)
    state = client.get(f"/rooms/{room['id']}", headers=users["admin"][0]).json()
    assert state["controller_user_id"] == users["admin"][1]


def test_admin_leaving_closes_room_and_clears_participants(client, db, users):
    room = _create(client, users["admin"][0])
    for name in ("bob", "carol"):
        client.post(f"/rooms/{room['id']}/join", headers=users[name][0])

    response = client.post(f"/rooms/{room['id']}/leave", headers=users["admin"][0])
    assert response.status_code == 200
    assert response.json() == {"message": "Room closed"}

    stored = db.get(MusicalRoom, room["id"])
    db.refresh(stored)
    assert stored.status == RoomStatus.CLOSED
    assert stored.is_playing is False
    assert stored.participants == []
    for name in ("bob", "carol"):
        gone = client.get(f"/rooms/{room['id']}", headers=users[name][0])
        assert gone.status_code == 410


def test_deleting_room_cascades_to_participants(client, db, users):
    room = _create(client, users["admin"][0])
    client.post(f"/rooms/{room['id']}/join", headers=users["bob"][0])

    db.delete(db.get(MusicalRoom, room["id"]))
    db.flush()
    assert db.get(RoomParticipant, (room["id"], users["bob"][1])) is None


# --- transfer access ----------------------------------------------------------------


def test_transfer_access_both_directions(client, users):
    room = _create(client, users["admin"][0])
    (admin_headers, admin_id), (bob_headers, bob_id) = users["admin"], users["bob"]
    client.post(f"/rooms/{room['id']}/join", headers=bob_headers)

    to_bob = client.post(
        f"/rooms/{room['id']}/transfer-access",
        json={"target_user_id": bob_id},
        headers=admin_headers,
    )
    assert to_bob.status_code == 200
    assert to_bob.json()["controller_user_id"] == bob_id

    back = client.post(
        f"/rooms/{room['id']}/transfer-access",
        json={"target_user_id": admin_id},
        headers=bob_headers,
    )
    assert back.status_code == 200
    assert back.json()["controller_user_id"] == admin_id


def test_admin_can_take_back_control_from_controller(client, users):
    room = _create(client, users["admin"][0])
    for name in ("bob", "carol"):
        client.post(f"/rooms/{room['id']}/join", headers=users[name][0])
    client.post(
        f"/rooms/{room['id']}/transfer-access",
        json={"target_user_id": users["bob"][1]},
        headers=users["admin"][0],
    )
    to_carol = client.post(
        f"/rooms/{room['id']}/transfer-access",
        json={"target_user_id": users["carol"][1]},
        headers=users["admin"][0],
    )
    assert to_carol.json()["controller_user_id"] == users["carol"][1]


def test_only_admin_or_controller_can_transfer(client, users):
    room = _create(client, users["admin"][0])
    for name in ("bob", "carol"):
        client.post(f"/rooms/{room['id']}/join", headers=users[name][0])

    response = client.post(
        f"/rooms/{room['id']}/transfer-access",
        json={"target_user_id": users["carol"][1]},
        headers=users["bob"][0],
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "NOT_ROOM_CONTROLLER"


def test_transfer_to_non_participant_is_403(client, users):
    room = _create(client, users["admin"][0])
    response = client.post(
        f"/rooms/{room['id']}/transfer-access",
        json={"target_user_id": users["bob"][1]},
        headers=users["admin"][0],
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "NOT_ROOM_PARTICIPANT"


# --- playback state written by the RT layer -----------------------------------------


@pytest.fixture
def room_with_bob(client, db, users, catalog):
    room = _create(client, users["admin"][0])
    client.post(f"/rooms/{room['id']}/join", headers=users["bob"][0])
    return room["id"]


def test_playback_event_requires_controller(db, users, room_with_bob):
    with pytest.raises(AppError) as exc:
        room_service.apply_playback_event(
            db, room_with_bob, user_id=users["bob"][1], event="play", position_seconds=0
        )
    assert exc.value.code == "NOT_ROOM_CONTROLLER"


def test_song_change_then_pause_seek_play_persist_state(db, users, catalog, room_with_bob):
    admin_id = users["admin"][1]
    song = next(iter(catalog.values()))

    room = room_service.apply_playback_event(
        db, room_with_bob, user_id=admin_id, event="song_change", position_seconds=0, song_id=song.id
    )
    assert room_service.playback_payload(room) == {
        "song_id": song.id,
        "position_seconds": 0.0,
        "is_playing": True,
    }

    room = room_service.apply_playback_event(
        db, room_with_bob, user_id=admin_id, event="pause", position_seconds=12.5
    )
    assert (room.is_playing, room.position_seconds) == (False, 12.5)

    room = room_service.apply_playback_event(
        db, room_with_bob, user_id=admin_id, event="seek", position_seconds=40
    )
    assert (room.is_playing, room.position_seconds) == (False, 40.0)

    room = room_service.apply_playback_event(
        db, room_with_bob, user_id=admin_id, event="play", position_seconds=40
    )
    assert room.is_playing is True


def test_seek_is_clamped_to_song_length(db, users, catalog, room_with_bob):
    admin_id = users["admin"][1]
    song = next(iter(catalog.values()))
    room_service.apply_playback_event(
        db, room_with_bob, user_id=admin_id, event="song_change", position_seconds=0, song_id=song.id
    )
    room = room_service.apply_playback_event(
        db, room_with_bob, user_id=admin_id, event="seek", position_seconds=99_999
    )
    assert room.position_seconds == float(song.duration_seconds)


def test_play_without_song_is_rejected(db, users, room_with_bob):
    with pytest.raises(AppError) as exc:
        room_service.apply_playback_event(
            db, room_with_bob, user_id=users["admin"][1], event="play", position_seconds=0
        )
    assert exc.value.code == "NO_CURRENT_SONG"


def test_song_change_to_unknown_song_is_rejected(db, users, room_with_bob):
    with pytest.raises(AppError) as exc:
        room_service.apply_playback_event(
            db,
            room_with_bob,
            user_id=users["admin"][1],
            event="song_change",
            position_seconds=0,
            song_id=999_999_999,
        )
    assert exc.value.code == "SONG_NOT_FOUND"


def test_new_controller_can_drive_playback_after_transfer(client, db, users, catalog, room_with_bob):
    client.post(
        f"/rooms/{room_with_bob}/transfer-access",
        json={"target_user_id": users["bob"][1]},
        headers=users["admin"][0],
    )
    song = next(iter(catalog.values()))
    room = room_service.apply_playback_event(
        db,
        room_with_bob,
        user_id=users["bob"][1],
        event="song_change",
        position_seconds=0,
        song_id=song.id,
    )
    assert room.current_song_id == song.id
    with pytest.raises(AppError):
        room_service.apply_playback_event(
            db, room_with_bob, user_id=users["admin"][1], event="pause", position_seconds=1
        )


# --- docs ---------------------------------------------------------------------------


def test_openapi_lists_room_endpoints(client):
    paths = client.get("/openapi.json").json()["paths"]
    assert "post" in paths["/rooms"]
    assert "get" in paths["/rooms/{room_id}"]
    for action in ("join", "leave", "transfer-access"):
        assert "post" in paths[f"/rooms/{{room_id}}/{action}"]

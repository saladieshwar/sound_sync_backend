"""Admin: upload songs, view users and active rooms, delete songs (ADM-01, ADM-02, ADM-04, ADM-05)."""

import io
import uuid
from pathlib import Path

import pytest
from sqlalchemy import func, select, update

from app.core.config import settings
from app.models import LikedSong, RecentlyPlayed, Song, User
from tests.conftest import DEFAULT_PASSWORD

WAV_BYTES = b"RIFF" + b"\x00" * 60
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 30


@pytest.fixture
def admin_headers(client, db, make_user):
    payload, _ = make_user(username="boss")
    db.execute(update(User).where(User.email == payload["email"]).values(is_admin=True))
    db.flush()
    token = client.post(
        "/auth/login", json={"email": payload["email"], "password": DEFAULT_PASSWORD}
    ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def media_files():
    """Paths of media files a test creates; any left over are removed afterwards."""
    paths: list[Path] = []
    yield paths
    for path in paths:
        path.unlink(missing_ok=True)


def media_path(url: str) -> Path:
    return Path(settings.MEDIA_ROOT) / url.removeprefix(settings.MEDIA_URL_PREFIX + "/")


def upload(client, headers, media_files, *, fields=None, audio=("song.wav", WAV_BYTES), cover=None):
    data = {
        "title": "  Upload Test  ",
        "artist": "QA Band",
        "album": "QA Album",
        "category": "test",
        "duration_seconds": "42",
        **(fields or {}),
    }
    files = {"audio_file": (audio[0], io.BytesIO(audio[1]), "audio/wav")}
    if cover:
        files["cover_file"] = (cover[0], io.BytesIO(cover[1]), "image/png")
    before = {p for sub in ("audio", "covers") for p in (Path(settings.MEDIA_ROOT) / sub).glob("*")}
    response = client.post("/admin/songs", data=data, files=files, headers=headers)
    after = {p for sub in ("audio", "covers") for p in (Path(settings.MEDIA_ROOT) / sub).glob("*")}
    media_files.extend(after - before)
    return response


# --- ADM-01 upload ------------------------------------------------------------------


def test_upload_creates_searchable_song_with_served_files(client, admin_headers, media_files):
    response = upload(client, admin_headers, media_files, cover=("cover.PNG", PNG_BYTES))
    assert response.status_code == 201, response.text
    song = response.json()
    assert song["title"] == "Upload Test"  # trimmed
    assert song["audio_url"].startswith("/media/audio/") and song["audio_url"].endswith(".wav")
    assert song["cover_url"].startswith("/media/covers/") and song["cover_url"].endswith(".png")

    assert media_path(song["audio_url"]).read_bytes() == WAV_BYTES
    served = client.get(song["audio_url"])
    assert served.status_code == 200
    assert served.content == WAV_BYTES
    assert client.get(song["cover_url"]).headers["content-type"] == "image/png"

    found = client.get("/songs/search", params={"q": "upload test"}).json()
    assert song["id"] in [s["id"] for s in found]


def test_upload_without_cover_or_album(client, admin_headers, media_files):
    response = upload(
        client, admin_headers, media_files, fields={"album": "  "}, audio=("track.MP3", b"ID3data")
    )
    assert response.status_code == 201, response.text
    assert response.json()["album"] is None
    assert response.json()["cover_url"] is None
    assert len(media_files) == 1


@pytest.mark.parametrize(
    ("audio", "cover", "field"),
    [
        (("evil.html", b"<script>alert(1)</script>"), None, "audio_file"),
        (("noext", WAV_BYTES), None, "audio_file"),
        (("song.wav", WAV_BYTES), ("cover.svg", b"<svg onload=alert(1)>"), "cover_file"),
    ],
)
def test_upload_rejects_unsupported_file_types(client, admin_headers, media_files, audio, cover, field):
    response = upload(client, admin_headers, media_files, audio=audio, cover=cover)
    assert response.status_code == 415
    error = response.json()["error"]
    assert error["code"] == "UNSUPPORTED_FILE_TYPE"
    assert error["details"]["field"] == field
    assert media_files == []  # nothing left on disk


def test_upload_rejects_oversized_files_and_cleans_up(client, admin_headers, media_files, monkeypatch, db):
    monkeypatch.setattr(settings, "MAX_COVER_UPLOAD_BYTES", 10)
    count = db.scalar(select(func.count()).select_from(Song))
    response = upload(client, admin_headers, media_files, cover=("big.png", PNG_BYTES))
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "FILE_TOO_LARGE"
    assert media_files == []  # the already-saved audio file was removed too
    assert db.scalar(select(func.count()).select_from(Song)) == count


def test_upload_rejects_empty_audio(client, admin_headers, media_files):
    response = upload(client, admin_headers, media_files, audio=("empty.wav", b""))
    assert response.status_code == 422
    assert media_files == []


@pytest.mark.parametrize(
    "fields",
    [{"title": "   "}, {"category": ""}, {"duration_seconds": "-1"}, {"title": "x" * 201}],
)
def test_upload_validates_metadata(client, admin_headers, media_files, fields):
    response = upload(client, admin_headers, media_files, fields=fields)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert media_files == []


# --- ADM-02 access ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "path"),
    [("post", "/admin/songs"), ("delete", "/admin/songs/1"), ("get", "/admin/users"), ("get", "/admin/rooms")],
)
def test_admin_routes_require_admin(client, auth_headers, method, path):
    assert getattr(client, method)(path).status_code == 401
    response = getattr(client, method)(path, headers=auth_headers)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "ADMIN_REQUIRED"


# --- ADM-04 users and rooms ---------------------------------------------------------


def test_admin_lists_users_without_secrets(client, admin_headers, make_user):
    _, alice = make_user(username="alice")
    users = client.get("/admin/users", params={"limit": 500}, headers=admin_headers).json()
    listed = next(u for u in users if u["id"] == alice["id"])
    assert listed["username"] == "alice"
    assert "password" not in str(users) and "password_hash" not in str(users)


def test_admin_lists_only_active_rooms_newest_first(client, admin_headers, login_headers):
    owner = login_headers()
    first = client.post("/rooms", json={"name": "First"}, headers=owner).json()["id"]
    closed = client.post("/rooms", json={"name": "Closed"}, headers=owner).json()["id"]
    newest = client.post("/rooms", json={"name": "Newest"}, headers=owner).json()["id"]
    client.post(f"/rooms/{closed}/leave", headers=owner)

    rooms = client.get("/admin/rooms", headers=admin_headers).json()
    ids = [r["id"] for r in rooms]
    assert closed not in ids
    assert ids.index(newest) < ids.index(first)
    assert next(r for r in rooms if r["id"] == first)["participants"][0]["user"]["username"] == "tester"


# --- ADM-05 delete ------------------------------------------------------------------


def test_admin_delete_removes_song_library_rows_and_files(client, db, admin_headers, auth_headers, media_files):
    song = upload(client, admin_headers, media_files, cover=("c.png", PNG_BYTES)).json()
    client.post(f"/users/me/liked-songs/{song['id']}", headers=auth_headers)
    client.post(f"/users/me/recently-played/{song['id']}", headers=auth_headers)

    assert client.delete(f"/admin/songs/{song['id']}", headers=admin_headers).status_code == 204

    assert client.get(f"/songs/{song['id']}").status_code == 404
    for model in (LikedSong, RecentlyPlayed):
        assert db.scalar(select(func.count()).select_from(model).where(model.song_id == song["id"])) == 0
    assert not media_path(song["audio_url"]).exists()
    assert not media_path(song["cover_url"]).exists()
    assert client.get(song["audio_url"]).status_code == 404


def test_admin_delete_keeps_files_other_songs_still_use(client, db, admin_headers, media_files):
    song = upload(client, admin_headers, media_files, cover=("c.png", PNG_BYTES)).json()
    twin = Song(
        title=f"Twin {uuid.uuid4().hex[:6]}", artist="QA", category="test", duration_seconds=1,
        audio_url="/media/audio/elsewhere.wav", cover_url=song["cover_url"],
    )
    db.add(twin)
    db.flush()

    assert client.delete(f"/admin/songs/{song['id']}", headers=admin_headers).status_code == 204
    assert not media_path(song["audio_url"]).exists()
    assert media_path(song["cover_url"]).exists()  # shared album cover stays


def test_admin_delete_unknown_song_is_404(client, admin_headers):
    response = client.delete("/admin/songs/0", headers=admin_headers)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "SONG_NOT_FOUND"

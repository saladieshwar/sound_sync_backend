"""MEDIA_STORAGE=database: uploads live in media_files (Render's free disk is wiped on restart)
and are served from the usual /media URLs, including range requests for audio seeking."""

import io
from pathlib import Path

import pytest
from sqlalchemy import func, select, update

from app.core.config import settings
from app.models import MediaFile, User
from tests.conftest import DEFAULT_PASSWORD

AUDIO = bytes(range(256)) * 40  # 10240 bytes
PNG = b"\x89PNG\r\n\x1a\n" + b"\x01" * 40


@pytest.fixture(autouse=True)
def database_storage(monkeypatch):
    monkeypatch.setattr(settings, "MEDIA_STORAGE", "database")
    monkeypatch.setattr(settings, "CLOUDINARY_URL", "")


@pytest.fixture
def admin_headers(client, db, make_user):
    payload, _ = make_user(username="dbboss")
    db.execute(update(User).where(User.email == payload["email"]).values(is_admin=True))
    db.flush()
    token = client.post(
        "/auth/login", json={"email": payload["email"], "password": DEFAULT_PASSWORD}
    ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def local_files() -> set[Path]:
    return {p for p in Path(settings.MEDIA_ROOT).rglob("*") if p.is_file()}


def upload_song(client, headers):
    return client.post(
        "/admin/songs",
        data={"title": "DB Song", "artist": "Rows", "category": "test", "duration_seconds": "12"},
        files={
            "audio_file": ("track.mp3", io.BytesIO(AUDIO), "audio/mpeg"),
            "cover_file": ("art.png", io.BytesIO(PNG), "image/png"),
        },
        headers=headers,
    )


def stored_keys(db) -> set[str]:
    return set(db.scalars(select(MediaFile.key)))


def test_production_defaults_to_database(monkeypatch):
    monkeypatch.setattr(settings, "MEDIA_STORAGE", "")
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    assert settings.media_in_database
    monkeypatch.setattr(settings, "ENVIRONMENT", "development")
    assert not settings.media_in_database


def test_upload_is_stored_in_database_and_served(client, db, admin_headers):
    before = local_files()
    response = upload_song(client, admin_headers)
    assert response.status_code == 201, response.text
    song = response.json()
    assert song["audio_url"].startswith("/media/audio/") and song["audio_url"].endswith(".mp3")
    assert local_files() == before  # nothing left on the (ephemeral) disk
    assert {song["audio_url"][7:], song["cover_url"][7:]} <= stored_keys(db)

    full = client.get(song["audio_url"])
    assert full.status_code == 200
    assert full.content == AUDIO
    assert full.headers["content-type"] == "audio/mpeg"
    assert full.headers["accept-ranges"] == "bytes"
    assert client.get(song["cover_url"]).headers["content-type"] == "image/png"

    part = client.get(song["audio_url"], headers={"Range": "bytes=100-199"})
    assert part.status_code == 206
    assert part.content == AUDIO[100:200]
    assert part.headers["content-range"] == f"bytes 100-199/{len(AUDIO)}"

    assert client.get(song["audio_url"], headers={"Range": "bytes=10000-"}).content == AUDIO[10000:]
    assert client.get(song["audio_url"], headers={"Range": "bytes=-40"}).content == AUDIO[-40:]
    bad = client.get(song["audio_url"], headers={"Range": f"bytes={len(AUDIO)}-"})
    assert bad.status_code == 416
    assert bad.headers["content-range"] == f"bytes */{len(AUDIO)}"

    head = client.head(song["audio_url"])
    assert head.status_code == 200 and head.headers["content-length"] == str(len(AUDIO))


def test_replace_cover_and_delete_song_remove_rows(client, db, admin_headers):
    song = upload_song(client, admin_headers).json()
    old_cover = song["cover_url"]
    replaced = client.put(
        f"/admin/songs/{song['id']}/cover",
        files={"cover_file": ("new.png", io.BytesIO(PNG + b"2"), "image/png")},
        headers=admin_headers,
    ).json()
    assert old_cover[7:] not in stored_keys(db)
    assert client.get(old_cover).status_code == 404
    assert client.get(replaced["cover_url"]).content == PNG + b"2"

    assert client.delete(f"/admin/songs/{song['id']}", headers=admin_headers).status_code in (200, 204)
    assert not {song["audio_url"][7:], replaced["cover_url"][7:]} & stored_keys(db)
    assert client.get(song["audio_url"]).status_code == 404


def test_rejected_upload_leaves_no_rows(client, db, admin_headers):
    count = db.scalar(select(func.count()).select_from(MediaFile))
    response = client.post(
        "/admin/songs",
        data={"title": "Too big", "artist": "X", "category": "test", "duration_seconds": "1"},
        files={
            "audio_file": ("ok.mp3", io.BytesIO(AUDIO), "audio/mpeg"),
            "cover_file": ("huge.png", io.BytesIO(b"\x00" * (settings.MAX_COVER_UPLOAD_BYTES + 1)), "image/png"),
        },
        headers=admin_headers,
    )
    assert response.status_code == 413
    assert db.scalar(select(func.count()).select_from(MediaFile)) == count


def test_avatar_in_database(client, db, make_user):
    payload, _ = make_user(username="dbavatar")
    token = client.post(
        "/auth/login", json={"email": payload["email"], "password": DEFAULT_PASSWORD}
    ).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    url = client.put(
        "/users/me/avatar", files={"avatar_file": ("me.png", io.BytesIO(PNG), "image/png")}, headers=headers
    ).json()["avatar_url"]
    assert client.get(url).content == PNG
    client.delete("/users/me/avatar", headers=headers)
    assert client.get(url).status_code == 404


def test_path_traversal_is_rejected(client):
    assert client.get("/media/../app/main.py").status_code == 404
    assert client.get("/media/%2e%2e/.env").status_code == 404

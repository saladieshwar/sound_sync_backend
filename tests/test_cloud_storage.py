"""Uploads go to Cloudinary when CLOUDINARY_URL is set (Render's free disk is wiped on restart)."""

import hashlib
import io
from pathlib import Path

import httpx
import pytest
from sqlalchemy import update

from app.core.config import settings
from app.models import User
from app.services import cloud_storage
from tests.conftest import DEFAULT_PASSWORD

CLOUD = "democloud"


@pytest.fixture
def cloudinary(monkeypatch):
    """Fakes the Cloudinary API; returns the list of requests it received."""
    monkeypatch.setattr(settings, "CLOUDINARY_URL", f"cloudinary://key123:secret456@{CLOUD}")
    calls = []

    def fake_post(url, data=None, files=None, timeout=None):
        calls.append({"url": url, "data": data, "file": files["file"][1].read() if files else None})
        request = httpx.Request("POST", url)
        if url.endswith("/upload"):
            kind = url.split("/")[-2]
            body = {"secure_url": f"https://res.cloudinary.com/{CLOUD}/{kind}/upload/v17/{data['folder']}/{data['public_id']}.bin"}
            return httpx.Response(200, json=body, request=request)
        return httpx.Response(200, json={"result": "ok"}, request=request)

    monkeypatch.setattr(cloud_storage.httpx, "post", fake_post)
    return calls


@pytest.fixture
def admin_headers(client, db, make_user):
    payload, _ = make_user(username="cloudboss")
    db.execute(update(User).where(User.email == payload["email"]).values(is_admin=True))
    db.flush()
    token = client.post(
        "/auth/login", json={"email": payload["email"], "password": DEFAULT_PASSWORD}
    ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_disabled_without_valid_url(monkeypatch):
    for value in ("", "https://example.com", "cloudinary://only-key@cloud"):
        monkeypatch.setattr(settings, "CLOUDINARY_URL", value)
        assert not cloud_storage.enabled()


def test_upload_song_stores_files_on_cloudinary_and_delete_removes_them(client, admin_headers, cloudinary):
    local_before = {p for p in Path(settings.MEDIA_ROOT).rglob("*") if p.is_file()}
    response = client.post(
        "/admin/songs",
        data={"title": "Cloud Song", "artist": "Sky", "category": "test", "duration_seconds": "30"},
        files={
            "audio_file": ("song.mp3", io.BytesIO(b"ID3audio"), "audio/mpeg"),
            "cover_file": ("cover.jpg", io.BytesIO(b"\xff\xd8jpeg"), "image/jpeg"),
        },
        headers=admin_headers,
    )
    assert response.status_code == 201, response.text
    song = response.json()
    assert song["audio_url"].startswith(f"https://res.cloudinary.com/{CLOUD}/video/upload/")
    assert song["cover_url"].startswith(f"https://res.cloudinary.com/{CLOUD}/image/upload/")
    assert {p for p in Path(settings.MEDIA_ROOT).rglob("*") if p.is_file()} == local_before

    audio_call, cover_call = cloudinary
    assert audio_call["url"].endswith(f"/{CLOUD}/video/upload") and audio_call["file"] == b"ID3audio"
    assert cover_call["url"].endswith(f"/{CLOUD}/image/upload")
    signed = {k: v for k, v in audio_call["data"].items() if k not in ("api_key", "signature")}
    expected = hashlib.sha1(
        ("&".join(f"{k}={signed[k]}" for k in sorted(signed)) + "secret456").encode()
    ).hexdigest()
    assert audio_call["data"]["signature"] == expected

    cloudinary.clear()
    assert client.delete(f"/admin/songs/{song['id']}", headers=admin_headers).status_code in (200, 204)
    destroyed = {(c["url"].split("/")[-2], c["data"]["public_id"]) for c in cloudinary}
    assert destroyed == {
        ("video", song["audio_url"].split("/upload/v17/")[1].removesuffix(".bin")),
        ("image", song["cover_url"].split("/upload/v17/")[1].removesuffix(".bin")),
    }


def test_owns_only_this_clouds_urls(cloudinary):
    assert cloud_storage.owns(f"https://res.cloudinary.com/{CLOUD}/image/upload/v1/soundsync/covers/a.jpg")
    assert not cloud_storage.owns("https://res.cloudinary.com/othercloud/image/upload/v1/a.jpg")
    assert not cloud_storage.owns("/media/covers/a.jpg")

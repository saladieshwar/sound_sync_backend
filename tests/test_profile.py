"""Profile: users edit their own details and profile picture."""

import io
from pathlib import Path

import pytest

from app.core.config import settings
from tests.conftest import DEFAULT_PASSWORD

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 30
AVATARS = Path(settings.MEDIA_ROOT) / "avatars"


def media_path(url: str) -> Path:
    return Path(settings.MEDIA_ROOT) / url.removeprefix(settings.MEDIA_URL_PREFIX + "/")


@pytest.fixture
def avatar_files():
    """Avatar files a test creates; any left over are removed afterwards."""
    before = set(AVATARS.glob("*"))
    yield
    for path in set(AVATARS.glob("*")) - before:
        path.unlink(missing_ok=True)


def put_avatar(client, headers, name="me.png", content=PNG_BYTES):
    return client.put(
        "/users/me/avatar", files={"avatar_file": (name, io.BytesIO(content), "image/png")}, headers=headers
    )


def test_new_users_have_an_empty_profile(client, make_user):
    _, user = make_user()
    for field in ("full_name", "phone", "bio", "avatar_url"):
        assert user[field] is None


def test_update_profile_saves_and_returns_the_details(client, auth_headers):
    body = {"username": "  riya ", "full_name": " Riya Sharma ", "phone": "+91 98765-43210", "bio": "Melody fan"}
    response = client.patch("/users/me", json=body, headers=auth_headers)
    assert response.status_code == 200, response.text
    user = response.json()
    assert (user["username"], user["full_name"], user["phone"], user["bio"]) == (
        "riya", "Riya Sharma", "+91 98765-43210", "Melody fan",
    )
    assert client.get("/auth/me", headers=auth_headers).json() == user


def test_update_profile_changes_only_the_fields_sent(client, auth_headers):
    client.patch("/users/me", json={"full_name": "Riya", "phone": "9876543210"}, headers=auth_headers)
    user = client.patch("/users/me", json={"bio": "Hi"}, headers=auth_headers).json()
    assert (user["full_name"], user["phone"], user["bio"], user["username"]) == ("Riya", "9876543210", "Hi", "tester")


def test_blank_details_are_cleared(client, auth_headers):
    client.patch("/users/me", json={"full_name": "Riya", "phone": "9876543210", "bio": "Hi"}, headers=auth_headers)
    user = client.patch("/users/me", json={"full_name": " ", "phone": "", "bio": None}, headers=auth_headers).json()
    assert (user["full_name"], user["phone"], user["bio"]) == (None, None, None)


@pytest.mark.parametrize(
    "body",
    [
        {"username": " "},
        {"username": None},
        {"username": "x" * 51},
        {"full_name": "x" * 101},
        {"bio": "x" * 301},
        {"phone": "12345"},
        {"phone": "call me maybe"},
        {"phone": "+1 234 567 890 123 456"},
        {"email": "new@soundsync.dev"},
        {"is_admin": True},
    ],
)
def test_update_profile_rejects_invalid_or_protected_fields(client, auth_headers, body):
    response = client.patch("/users/me", json=body, headers=auth_headers)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    me = client.get("/auth/me", headers=auth_headers).json()
    assert me["username"] == "tester" and me["is_admin"] is False


def test_profile_changes_only_the_signed_in_user(client, login_headers, make_user):
    other_payload, _ = make_user(username="other")
    client.patch("/users/me", json={"full_name": "Changed"}, headers=login_headers())
    token = client.post(
        "/auth/login", json={"email": other_payload["email"], "password": DEFAULT_PASSWORD}
    ).json()["access_token"]
    other = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"}).json()
    assert other["full_name"] is None


@pytest.mark.parametrize(
    ("method", "path"), [("patch", "/users/me"), ("put", "/users/me/avatar"), ("delete", "/users/me/avatar")]
)
def test_profile_routes_require_login(client, method, path):
    response = getattr(client, method)(path)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_TOKEN"


def test_avatar_upload_is_stored_served_and_replaced(client, auth_headers, avatar_files):
    first = put_avatar(client, auth_headers)
    assert first.status_code == 200, first.text
    first_url = first.json()["avatar_url"]
    assert first_url.startswith("/media/avatars/") and first_url.endswith(".png")
    assert client.get(first_url).content == PNG_BYTES

    second_url = put_avatar(client, auth_headers, name="new.JPG").json()["avatar_url"]
    assert second_url.endswith(".jpg") and second_url != first_url
    assert not media_path(first_url).exists()  # the old picture is deleted
    assert client.get("/auth/me", headers=auth_headers).json()["avatar_url"] == second_url


def test_avatar_remove_deletes_the_file(client, auth_headers, avatar_files):
    url = put_avatar(client, auth_headers).json()["avatar_url"]
    response = client.delete("/users/me/avatar", headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["avatar_url"] is None
    assert not media_path(url).exists()
    assert client.delete("/users/me/avatar", headers=auth_headers).status_code == 200  # nothing to remove


@pytest.mark.parametrize(
    ("name", "content", "status", "code"),
    [
        ("evil.svg", b"<svg onload=alert(1)>", 415, "UNSUPPORTED_FILE_TYPE"),
        ("page.html", b"<script>alert(1)</script>", 415, "UNSUPPORTED_FILE_TYPE"),
        ("empty.png", b"", 422, "VALIDATION_ERROR"),
    ],
)
def test_avatar_rejects_bad_files_and_keeps_the_old_one(client, auth_headers, avatar_files, name, content, status, code):
    url = put_avatar(client, auth_headers).json()["avatar_url"]
    before = set(AVATARS.glob("*"))
    response = put_avatar(client, auth_headers, name=name, content=content)
    assert response.status_code == status
    assert response.json()["error"]["code"] == code
    assert set(AVATARS.glob("*")) == before  # nothing new left on disk
    assert client.get("/auth/me", headers=auth_headers).json()["avatar_url"] == url
    assert media_path(url).is_file()


def test_avatar_rejects_oversized_files(client, auth_headers, avatar_files, monkeypatch):
    monkeypatch.setattr(settings, "MAX_COVER_UPLOAD_BYTES", 10)
    response = put_avatar(client, auth_headers)
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "FILE_TOO_LARGE"
    assert client.get("/auth/me", headers=auth_headers).json()["avatar_url"] is None

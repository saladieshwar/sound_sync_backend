"""Phase 2 auth acceptance tests (acceptance matrix AUTH-01..AUTH-07, ADM-02, RES-01)."""

from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core.config import Settings, settings
from app.core.security import create_access_token, verify_password
from app.main import create_app
from app.models import User
from app.services import auth_service

SENSITIVE_KEYS = {"password", "password_hash"}


def _assert_error(response, status_code: int, code: str):
    assert response.status_code == status_code, response.text
    body = response.json()
    assert set(body) == {"error"}
    assert body["error"]["code"] == code
    assert isinstance(body["error"]["message"], str)
    return body["error"]


def _token_for(user_id: int, **overrides) -> str:
    now = datetime.now(timezone.utc)
    payload = {"sub": str(user_id), "iat": now, "exp": now + timedelta(minutes=5), **overrides}
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


# --- Register ---------------------------------------------------------------


def test_register_returns_user_without_password_fields(client, make_user):
    payload, user = make_user(username="  alice  ")
    assert user["email"] == payload["email"]
    assert user["username"] == "alice"
    assert user["is_admin"] is False
    assert SENSITIVE_KEYS.isdisjoint(user)


def test_register_normalizes_email_to_lowercase(client, make_user):
    _, user = make_user(email="Mixed.Case@SoundSync.dev")
    assert user["email"] == "mixed.case@soundsync.dev"


def test_register_duplicate_email_rejected(client, make_user):
    payload, _ = make_user()
    response = client.post("/auth/register", json=payload)
    _assert_error(response, 409, "EMAIL_ALREADY_REGISTERED")


def test_register_duplicate_email_is_case_insensitive(client, make_user):
    payload, _ = make_user(email="dup@soundsync.dev")
    response = client.post("/auth/register", json={**payload, "email": "DUP@soundsync.dev"})
    _assert_error(response, 409, "EMAIL_ALREADY_REGISTERED")


def test_register_concurrent_duplicate_returns_409_not_500(client, make_user, monkeypatch):
    payload, _ = make_user()
    # Simulate a race: the pre-insert existence check misses the existing row.
    monkeypatch.setattr(auth_service.user_repo, "get_by_email", lambda db, email: None)
    response = client.post("/auth/register", json=payload)
    _assert_error(response, 409, "EMAIL_ALREADY_REGISTERED")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("email", "not-an-email"),
        ("password", "short"),
        ("password", "x" * 73),
        ("password", "ü" * 37),  # 37 chars but 74 bytes: over bcrypt's limit
        ("username", " "),
    ],
)
def test_register_invalid_input_rejected(client, field, value):
    payload = {"username": "valid", "email": "valid@soundsync.dev", "password": "valid-pass"}
    response = client.post("/auth/register", json={**payload, field: value})
    error = _assert_error(response, 422, "VALIDATION_ERROR")
    assert error["details"]["errors"][0]["loc"][-1] == field


def test_password_is_stored_as_bcrypt_hash_never_plaintext(client, db, make_user):
    payload, user = make_user()
    stored = db.get(User, user["id"])
    assert stored.password_hash != payload["password"]
    assert stored.password_hash.startswith("$2")
    assert verify_password(payload["password"], stored.password_hash)


# --- Login ------------------------------------------------------------------


def test_login_returns_jwt_and_user(client, make_user):
    payload, user = make_user()
    response = client.post(
        "/auth/login", json={"email": payload["email"], "password": payload["password"]}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["user"]["id"] == user["id"]
    assert SENSITIVE_KEYS.isdisjoint(body["user"])
    claims = jwt.decode(
        body["access_token"], settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM]
    )
    assert claims["sub"] == str(user["id"])
    assert claims["exp"] > claims["iat"]


def test_login_email_is_case_insensitive(client, make_user):
    payload, _ = make_user()
    response = client.post(
        "/auth/login", json={"email": payload["email"].upper(), "password": payload["password"]}
    )
    assert response.status_code == 200


def test_login_wrong_password_and_unknown_email_look_identical(client, make_user):
    payload, _ = make_user()
    wrong_password = client.post(
        "/auth/login", json={"email": payload["email"], "password": "wrong-password"}
    )
    unknown_email = client.post(
        "/auth/login", json={"email": "nobody@soundsync.dev", "password": "wrong-password"}
    )
    first = _assert_error(wrong_password, 401, "INVALID_CREDENTIALS")
    second = _assert_error(unknown_email, 401, "INVALID_CREDENTIALS")
    assert first["message"] == second["message"]


def test_login_overlong_password_is_validation_error(client):
    response = client.post(
        "/auth/login", json={"email": "a@soundsync.dev", "password": "x" * 100}
    )
    _assert_error(response, 422, "VALIDATION_ERROR")


def test_no_auth_response_contains_the_plaintext_password(client, make_user):
    payload, _ = make_user()
    login = client.post(
        "/auth/login", json={"email": payload["email"], "password": payload["password"]}
    )
    me = client.get("/auth/me", headers={"Authorization": f"Bearer {login.json()['access_token']}"})
    duplicate = client.post("/auth/register", json=payload)
    for response in (login, me, duplicate):
        assert payload["password"] not in response.text


# --- Protected routes / get_current_user -----------------------------------


def test_me_with_valid_token(client, make_user):
    payload, user = make_user()
    token = client.post(
        "/auth/login", json={"email": payload["email"], "password": payload["password"]}
    ).json()["access_token"]
    response = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.json()["id"] == user["id"]


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Bearer not-a-jwt"},
        {"Authorization": "Basic dXNlcjpwYXNz"},
        {"Authorization": "Bearer "},
    ],
    ids=["missing", "garbage", "wrong-scheme", "empty"],
)
def test_me_rejects_missing_or_malformed_token(client, headers):
    _assert_error(client.get("/auth/me", headers=headers), 401, "INVALID_TOKEN")


def test_me_rejects_expired_token(client, make_user):
    _, user = make_user()
    past = datetime.now(timezone.utc) - timedelta(hours=2)
    token = _token_for(user["id"], iat=past, exp=past + timedelta(minutes=5))
    _assert_error(
        client.get("/auth/me", headers={"Authorization": f"Bearer {token}"}), 401, "INVALID_TOKEN"
    )


def test_me_rejects_token_signed_with_another_secret(client, make_user):
    _, user = make_user()
    now = datetime.now(timezone.utc)
    forged = jwt.encode(
        {"sub": str(user["id"]), "exp": now + timedelta(minutes=5)},
        "attacker-secret-that-is-long-enough-for-hs256",
        algorithm="HS256",
    )
    _assert_error(
        client.get("/auth/me", headers={"Authorization": f"Bearer {forged}"}), 401, "INVALID_TOKEN"
    )


def test_me_rejects_token_without_exp(client, make_user):
    _, user = make_user()
    token = jwt.encode(
        {"sub": str(user["id"])}, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM
    )
    _assert_error(
        client.get("/auth/me", headers={"Authorization": f"Bearer {token}"}), 401, "INVALID_TOKEN"
    )


def test_me_rejects_token_for_unknown_user(client):
    token = create_access_token(999_999_999)
    _assert_error(
        client.get("/auth/me", headers={"Authorization": f"Bearer {token}"}), 401, "INVALID_TOKEN"
    )


def test_protected_library_route_requires_token(client):
    _assert_error(client.get("/users/me/liked-songs"), 401, "INVALID_TOKEN")


def test_admin_route_forbidden_for_regular_user(client, auth_headers):
    _assert_error(client.get("/admin/users", headers=auth_headers), 403, "ADMIN_REQUIRED")


# --- Structured errors & config --------------------------------------------


def test_unknown_route_uses_structured_error(client):
    _assert_error(client.get("/does-not-exist"), 404, "NOT_FOUND")


def test_unhandled_exception_returns_structured_500():
    app = create_app()

    @app.get("/boom")
    def boom():
        raise RuntimeError("secret internal detail")

    response = TestClient(app, raise_server_exceptions=False).get("/boom")
    error = _assert_error(response, 500, "INTERNAL_ERROR")
    assert "secret internal detail" not in response.text
    assert error["message"] == "Internal server error"


@pytest.mark.parametrize("secret", ["change-me", "change-me-to-a-long-random-string", "short"])
def test_weak_jwt_secret_rejected_outside_development(secret):
    with pytest.raises(ValidationError):
        Settings(ENVIRONMENT="production", JWT_SECRET_KEY=secret, _env_file=None)


def test_strong_jwt_secret_accepted_in_production():
    Settings(ENVIRONMENT="production", JWT_SECRET_KEY="x" * 48, _env_file=None)

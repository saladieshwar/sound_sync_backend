"""Shared fixtures. Tests run against PostgreSQL (TEST_DATABASE_URL, or DATABASE_URL from .env)
inside a transaction that is rolled back after each test, so no data is left behind."""

import os
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db
from app.main import app
from app.models import Song
from scripts.seed import SONGS as SEED_SONGS
from scripts.seed import cover_url_for

_engine = create_engine(os.getenv("TEST_DATABASE_URL", settings.DATABASE_URL))

DEFAULT_PASSWORD = "s3cret-pass"


@pytest.fixture
def db():
    connection = _engine.connect()
    transaction = connection.begin()
    session = Session(
        bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False
    )
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture
def client(db):
    app.dependency_overrides[get_db] = lambda: db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.fixture
def make_user(client):
    """Registers a user via the API and returns (registration_payload, response_json)."""

    def _make(email: str | None = None, password: str = DEFAULT_PASSWORD, username: str = "tester"):
        payload = {
            "username": username,
            "email": email or f"user_{uuid.uuid4().hex[:10]}@soundsync.dev",
            "password": password,
        }
        response = client.post("/auth/register", json=payload)
        assert response.status_code == 201, response.text
        return payload, response.json()

    return _make


@pytest.fixture
def login_headers(client, make_user):
    """Factory: registers and logs in a fresh user; returns Authorization headers."""

    def _login(**user_fields) -> dict[str, str]:
        payload, _ = make_user(**user_fields)
        token = client.post(
            "/auth/login", json={"email": payload["email"], "password": payload["password"]}
        ).json()["access_token"]
        return {"Authorization": f"Bearer {token}"}

    return _login


@pytest.fixture
def auth_headers(login_headers):
    """Authorization headers for one fresh user."""
    return login_headers()


@pytest.fixture
def catalog(db):
    """Replaces the songs table (inside the test transaction) with exactly the seed catalog.
    Returns {title: Song}."""
    db.execute(delete(Song))
    songs = {}
    for i, s in enumerate(SEED_SONGS, start=1):
        song = Song(**s, audio_url=f"/media/audio/sample-{i}.mp3", cover_url=cover_url_for(s["album"]))
        db.add(song)
        songs[s["title"]] = song
    db.flush()
    return songs

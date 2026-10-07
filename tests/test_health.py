from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from app.db.session import get_db
from app.main import app

client = TestClient(app)


def test_health_ok():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ready_reports_database_up(client):
    response = client.get("/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ready", "database": "up"}


def test_ready_is_503_when_database_is_down():
    class DownSession:
        def execute(self, *_):
            raise OperationalError("SELECT 1", {}, Exception("connection refused"))

    app.dependency_overrides[get_db] = lambda: DownSession()
    try:
        response = client.get("/ready")
    finally:
        app.dependency_overrides.pop(get_db, None)
    assert response.status_code == 503
    assert response.json() == {"status": "unavailable", "database": "down"}
    assert client.get("/health").status_code == 200


def test_protected_route_requires_token():
    response = client.get("/auth/me")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_TOKEN"


def test_openapi_exposes_core_routes():
    paths = client.get("/openapi.json").json()["paths"]
    for route in (
        "/auth/register",
        "/auth/login",
        "/songs/search",
        "/users/me/liked-songs/{song_id}",
        "/users/me/recently-played",
        "/rooms",
        "/rooms/{room_id}/join",
        "/rooms/{room_id}/leave",
        "/rooms/{room_id}/transfer-access",
        "/admin/songs",
    ):
        assert route in paths, route

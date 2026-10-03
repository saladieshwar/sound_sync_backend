from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_ok():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


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

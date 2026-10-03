"""Phase 3 library API (acceptance matrix LIB-01..LIB-06): liked songs and recently played."""

import pytest

LIKED = "/users/me/liked-songs"
RECENT = "/users/me/recently-played"


def liked_titles(client, headers) -> list[str]:
    response = client.get(LIKED, headers=headers)
    assert response.status_code == 200
    return [item["song"]["title"] for item in response.json()]


def recent_titles(client, headers, **params) -> list[str]:
    response = client.get(RECENT, headers=headers, params=params)
    assert response.status_code == 200
    return [item["song"]["title"] for item in response.json()]


# --- auth -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", LIKED),
        ("post", f"{LIKED}/1"),
        ("delete", f"{LIKED}/1"),
        ("get", RECENT),
        ("post", f"{RECENT}/1"),
    ],
)
@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer not-a-jwt"}])
def test_library_requires_valid_jwt(client, method, path, headers):
    response = client.request(method, path, headers=headers)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_TOKEN"


def test_new_user_library_is_empty(client, auth_headers):
    assert liked_titles(client, auth_headers) == []
    assert recent_titles(client, auth_headers) == []


# --- liked songs ------------------------------------------------------------


def test_lib01_like_then_list_newest_first(client, catalog, auth_headers):
    for title in ["Rise Up", "Grey Rain", "Only You"]:
        response = client.post(f"{LIKED}/{catalog[title].id}", headers=auth_headers)
        assert response.status_code == 201
        body = response.json()
        assert body["song"]["title"] == title
        assert "liked_at" in body

    assert liked_titles(client, auth_headers) == ["Only You", "Grey Rain", "Rise Up"]


def test_lib02_like_twice_is_idempotent(client, catalog, auth_headers):
    song_id = catalog["Heartstrings"].id
    first = client.post(f"{LIKED}/{song_id}", headers=auth_headers)
    second = client.post(f"{LIKED}/{song_id}", headers=auth_headers)
    assert first.status_code == second.status_code == 201
    assert first.json()["liked_at"] == second.json()["liked_at"]
    assert liked_titles(client, auth_headers) == ["Heartstrings"]


def test_lib03_unlike_removes_song(client, catalog, auth_headers):
    keep, drop = catalog["Keep Going"].id, catalog["Moonlit Path"].id
    client.post(f"{LIKED}/{keep}", headers=auth_headers)
    client.post(f"{LIKED}/{drop}", headers=auth_headers)

    response = client.delete(f"{LIKED}/{drop}", headers=auth_headers)
    assert response.status_code == 204
    assert response.content == b""
    assert liked_titles(client, auth_headers) == ["Keep Going"]


def test_unlike_song_that_is_not_liked_is_noop(client, catalog, auth_headers):
    response = client.delete(f"{LIKED}/{catalog['Rise Up'].id}", headers=auth_headers)
    assert response.status_code == 204


def test_like_unlike_like_again(client, catalog, auth_headers):
    song_id = catalog["Letters Unsent"].id
    client.post(f"{LIKED}/{song_id}", headers=auth_headers)
    client.delete(f"{LIKED}/{song_id}", headers=auth_headers)
    assert liked_titles(client, auth_headers) == []
    client.post(f"{LIKED}/{song_id}", headers=auth_headers)
    assert liked_titles(client, auth_headers) == ["Letters Unsent"]


def test_lib04_like_unknown_song_is_404(client, catalog, auth_headers):
    response = client.post(f"{LIKED}/999999999", headers=auth_headers)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "SONG_NOT_FOUND"
    assert liked_titles(client, auth_headers) == []


# --- recently played --------------------------------------------------------


def test_lib05_recently_played_most_recent_first(client, catalog, auth_headers):
    a, b = catalog["Evening Breeze"].id, catalog["Grey Rain"].id
    for song_id in [a, b, a]:
        response = client.post(f"{RECENT}/{song_id}", headers=auth_headers)
        assert response.status_code == 201
        assert "played_at" in response.json()

    assert recent_titles(client, auth_headers) == ["Evening Breeze", "Grey Rain", "Evening Breeze"]

    played_at = [item["played_at"] for item in client.get(RECENT, headers=auth_headers).json()]
    assert played_at == sorted(played_at, reverse=True)


def test_recently_played_limit(client, catalog, auth_headers):
    for title in ["Rise Up", "Keep Going", "Only You"]:
        client.post(f"{RECENT}/{catalog[title].id}", headers=auth_headers)
    assert recent_titles(client, auth_headers, limit=2) == ["Only You", "Keep Going"]


@pytest.mark.parametrize("limit", [0, -1, 101])
def test_recently_played_rejects_bad_limit(client, auth_headers, limit):
    response = client.get(RECENT, headers=auth_headers, params={"limit": limit})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_log_play_unknown_song_is_404(client, catalog, auth_headers):
    response = client.post(f"{RECENT}/999999999", headers=auth_headers)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "SONG_NOT_FOUND"


# --- isolation / integrity --------------------------------------------------


def test_lib06_library_is_isolated_per_user(client, catalog, login_headers):
    alice, bob = login_headers(username="alice"), login_headers(username="bob")
    client.post(f"{LIKED}/{catalog['Rise Up'].id}", headers=alice)
    client.post(f"{RECENT}/{catalog['Grey Rain'].id}", headers=alice)

    assert liked_titles(client, bob) == []
    assert recent_titles(client, bob) == []

    client.delete(f"{LIKED}/{catalog['Rise Up'].id}", headers=bob)
    assert liked_titles(client, alice) == ["Rise Up"]


def test_deleting_song_removes_it_from_libraries(client, db, catalog, auth_headers):
    song = catalog["Only You"]
    client.post(f"{LIKED}/{song.id}", headers=auth_headers)
    client.post(f"{RECENT}/{song.id}", headers=auth_headers)

    db.delete(song)
    db.flush()
    db.expire_all()

    assert liked_titles(client, auth_headers) == []
    assert recent_titles(client, auth_headers) == []


def test_openapi_library_endpoints_require_bearer(client):
    paths = client.get("/openapi.json").json()["paths"]
    expected = {LIKED: {"get"}, f"{LIKED}/{{song_id}}": {"post", "delete"},
                RECENT: {"get"}, f"{RECENT}/{{song_id}}": {"post"}}
    for path, methods in expected.items():
        for method in methods:
            assert paths[path][method]["security"] == [{"HTTPBearer": []}], (path, method)

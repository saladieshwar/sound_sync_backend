"""Phase 3 catalog API (acceptance matrix CAT-01..CAT-06) against the seed catalog."""

import pytest

from app.models import Song


def titles(response) -> list[str]:
    return [song["title"] for song in response.json()]


# --- listing / detail -------------------------------------------------------


def test_list_songs_returns_seed_catalog_in_id_order(client, catalog):
    response = client.get("/songs")
    assert response.status_code == 200
    assert titles(response) == list(catalog)


def test_list_songs_pagination(client, catalog):
    all_titles = list(catalog)
    response = client.get("/songs", params={"skip": 2, "limit": 3})
    assert response.status_code == 200
    assert titles(response) == all_titles[2:5]


@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 201}, {"skip": -1}])
def test_list_songs_rejects_bad_pagination(client, catalog, params):
    response = client.get("/songs", params=params)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_song_shape(client, catalog):
    song = catalog["Rise Up"]
    body = client.get(f"/songs/{song.id}").json()
    assert body.pop("created_at")
    assert body == {
        "id": song.id,
        "title": "Rise Up",
        "artist": "Peak Drive",
        "album": "Unstoppable",
        "category": "motivation",
        "duration_seconds": 187,
        "audio_url": song.audio_url,
        "cover_url": "/media/covers/unstoppable.svg",
    }


def test_cat06_unknown_song_is_404(client, catalog):
    response = client.get("/songs/999999999")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "SONG_NOT_FOUND"


def test_non_integer_song_id_is_422(client, catalog):
    response = client.get("/songs/abc")
    assert response.status_code == 422


# --- search -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("q", "expected"),
    [
        ("rise", ["Rise Up"]),  # partial title
        ("HEART", ["Heartstrings"]),  # case-insensitive
        ("aria nova", ["Evening Breeze", "Moonlit Path"]),  # artist
        ("quiet rooms", ["Grey Rain", "Letters Unsent"]),  # album
        ("  only you  ", ["Only You"]),  # surrounding whitespace ignored
        ("o", ["Evening Breeze", "Grey Rain", "Heartstrings", "Keep Going", "Letters Unsent",
               "Moonlit Path", "Only You", "Rise Up"]),  # sorted by title
    ],
)
def test_cat01_search_matches(client, catalog, q, expected):
    response = client.get("/songs/search", params={"q": q})
    assert response.status_code == 200
    assert titles(response) == expected


@pytest.mark.parametrize("q", ["zzz-no-such-song", "%", "_", "\\", "R_se", "%Up"])
def test_cat02_search_no_match_returns_empty_list(client, catalog, q):
    response = client.get("/songs/search", params={"q": q})
    assert response.status_code == 200
    assert response.json() == []


def test_search_treats_wildcards_literally(client, db, catalog):
    db.add(Song(title="100% Pure", artist="Odd_Chars", category="melody", audio_url="/x.mp3"))
    db.flush()
    assert titles(client.get("/songs/search", params={"q": "100%"})) == ["100% Pure"]
    assert titles(client.get("/songs/search", params={"q": "odd_c"})) == ["100% Pure"]


@pytest.mark.parametrize("params", [{}, {"q": ""}, {"q": "   "}, {"q": "x" * 101}])
def test_cat03_search_invalid_query_is_422(client, catalog, params):
    response = client.get("/songs/search", params=params)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


# --- categories -------------------------------------------------------------


def test_list_categories(client, catalog):
    assert client.get("/songs/categories").json() == ["love", "melody", "motivation", "sad"]


@pytest.mark.parametrize(
    ("category", "expected"),
    [
        ("melody", ["Evening Breeze", "Moonlit Path"]),
        ("love", ["Heartstrings", "Only You"]),
        ("motivation", ["Keep Going", "Rise Up"]),
        ("sad", ["Grey Rain", "Letters Unsent"]),
        ("SAD", ["Grey Rain", "Letters Unsent"]),
    ],
)
def test_cat04_category_filter(client, catalog, category, expected):
    response = client.get(f"/songs/category/{category}")
    assert response.status_code == 200
    assert titles(response) == expected
    assert {s["category"] for s in response.json()} == {category.lower()}


def test_unknown_category_returns_empty_list(client, catalog):
    response = client.get("/songs/category/jazz")
    assert response.status_code == 200
    assert response.json() == []


# --- albums -----------------------------------------------------------------


def test_cat05_list_albums(client, catalog):
    response = client.get("/songs/albums")
    assert response.status_code == 200
    assert response.json() == [
        {"name": "Calm Skies", "artist": "Aria Nova", "cover_url": "/media/covers/calm-skies.svg", "song_count": 2},
        {"name": "Forever Yours", "artist": "The Lovelines", "cover_url": "/media/covers/forever-yours.svg", "song_count": 2},
        {"name": "Quiet Rooms", "artist": "Blue Hours", "cover_url": "/media/covers/quiet-rooms.svg", "song_count": 2},
        {"name": "Unstoppable", "artist": "Peak Drive", "cover_url": "/media/covers/unstoppable.svg", "song_count": 2},
    ]


def test_cat05_album_songs(client, catalog):
    response = client.get("/songs/album/Forever Yours")
    assert response.status_code == 200
    assert titles(response) == ["Heartstrings", "Only You"]
    assert client.get("/songs/album/Nope").json() == []


# --- contract ---------------------------------------------------------------


def test_catalog_is_public(client, catalog):
    for path in ["/songs", "/songs/categories", "/songs/albums", "/songs/category/sad",
                 "/songs/search?q=rain", f"/songs/{catalog['Grey Rain'].id}"]:
        assert client.get(path).status_code == 200, path


def test_openapi_lists_all_song_endpoints(client):
    paths = client.get("/openapi.json").json()["paths"]
    for path in ["/songs", "/songs/search", "/songs/categories", "/songs/category/{name}",
                 "/songs/albums", "/songs/album/{name}", "/songs/{song_id}"]:
        assert "get" in paths[path], path
        assert "security" not in paths[path]["get"], path

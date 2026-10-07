"""Phase 6 DATA: catalog search and room-join lookups stay on their indexes (plan-shape guards).

Full-size timings live in `python -m scripts.benchmark_catalog_rooms`; these run a smaller seed
inside the rolled-back test transaction so they are fast and leave no data behind.
"""

import pytest
from sqlalchemy.orm import Session

from app.repositories import song_repo
from scripts.benchmark_catalog_rooms import (
    explain_room_lookups,
    explain_search,
    seed_catalog,
    seed_rooms,
    time_joins,
)


@pytest.fixture
def big_catalog(db):
    conn = db.connection()
    seed_catalog(conn, songs=5000)
    return conn


@pytest.fixture
def busy_rooms(db):
    conn = db.connection()
    seed_rooms(conn, rooms=1000, per_room=5)
    return conn


@pytest.mark.parametrize("term", ["c4ca4", "Artist 1234", "ALBUM 0042", "no-such-song-xyz"])
def test_search_of_three_plus_chars_uses_the_trigram_index(big_catalog, term):
    plan = explain_search(big_catalog, term)
    assert "ix_songs_search_trgm" in plan["indexes"], plan
    assert "Seq Scan" not in plan["node_types"]
    assert plan["execution_ms"] < 25


def test_search_matches_any_field_case_insensitively_but_not_across_fields(big_catalog, db):
    session = Session(bind=big_catalog)
    assert all("artist 1234" in s.artist.lower() for s in song_repo.search(session, "ARTIST 1234"))
    assert song_repo.search(session, "album 0042")
    # "<artist> <album>" would only match if fields were glued together without a separator.
    assert song_repo.search(session, "1234Album") == []
    assert song_repo.search(session, "1234\x1fAlbum") == []


@pytest.mark.parametrize("lookup", ["participant", "room_participants", "user_rooms", "rooms_by_admin"])
def test_room_lookups_use_indexes(busy_rooms, lookup):
    plan = explain_room_lookups(busy_rooms)[lookup]
    assert plan["indexes"], plan
    assert "Seq Scan" not in plan["node_types"]
    assert plan["execution_ms"] < 5


def test_room_join_flow_meets_budget(busy_rooms):
    timings = time_joins(busy_rooms, joins=30)
    assert timings["joins"] == 30
    assert timings["room_size"] == 6
    assert timings["p95_ms"] < 50

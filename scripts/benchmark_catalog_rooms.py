"""Phase 6 DATA benchmark: catalog search and Musical Room join against a large synthetic dataset.

Run from backend/: python -m scripts.benchmark_catalog_rooms [songs] [rooms] [participants_per_room]

Everything happens inside one transaction that is rolled back, so the database is unchanged.
Budgets (p95, wall-clock through the same repository/service code the API runs):
  search, 3+ chars   <= SEARCH_P95_MS        (trigram index; song_repo.search, ORM mapping included)
  search, 1-2 chars  <= SHORT_SEARCH_P95_MS  (no trigram exists, so a scan of search_text)
  join               <= JOIN_P95_MS          (room_service.join_room + to_room_out: room read,
                                              participant check, insert, commit, participant reload)
"""

import statistics
import sys
import time

from sqlalchemy import Connection, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session

from app.db.session import engine
from app.repositories import song_repo
from app.services import room_service

SEARCH_P95_MS = 25.0
SHORT_SEARCH_P95_MS = 100.0
JOIN_P95_MS = 50.0
BENCH_EMAIL = "%@bench-rooms.soundsync.dev"

# Typical searches: a rare title fragment, an artist, an album, a broad 1-2 letter prefix, a miss.
SEARCH_TERMS = ("c4ca4", "artist 1234", "album 0042", "lo", "a", "no-such-song-xyz")


def seed_catalog(conn: Connection, songs: int) -> None:
    conn.execute(
        text(
            """
            INSERT INTO songs (title, artist, album, category, duration_seconds, audio_url)
            SELECT 'Track ' || md5(g::text),
                   'Artist ' || lpad((g % 5000)::text, 4, '0'),
                   'Album ' || lpad((g % 8000)::text, 4, '0'),
                   (ARRAY['love','melody','motivation','sad','rock','pop','jazz','lofi'])[1 + g % 8],
                   120 + g % 240,
                   '/media/audio/bench-' || g || '.wav'
            FROM generate_series(1, :songs) AS g
            """
        ),
        {"songs": songs},
    )
    # Bulk inserts sit in the GIN pending list until (auto)vacuum merges them; merge now so the
    # plans match a steady-state catalog rather than one mid-import.
    conn.execute(text("SELECT gin_clean_pending_list('ix_songs_search_trgm')"))
    conn.execute(text("ANALYZE songs"))


def seed_rooms(conn: Connection, rooms: int, per_room: int) -> None:
    """`rooms` active rooms, each with `per_room` participants, plus 200 spare users who join later."""
    users = rooms * per_room + 200
    conn.execute(
        text(
            """
            INSERT INTO users (username, email, password_hash, is_admin)
            SELECT 'rb' || g, 'rb' || g || '@bench-rooms.soundsync.dev', '$2b$12$' || repeat('a', 53), false
            FROM generate_series(1, :users) AS g
            """
        ),
        {"users": users},
    )
    conn.execute(
        text(
            """
            WITH u AS (
                SELECT id, row_number() OVER (ORDER BY id) AS n FROM users WHERE email LIKE :pattern
            )
            INSERT INTO musical_rooms (id, name, admin_user_id, controller_user_id, status,
                                       is_playing, position_seconds)
            SELECT 'B' || upper(substr(md5(n::text), 1, 7)), 'Bench room ' || n, id, id, 'active',
                   false, 0
            FROM u WHERE n <= :rooms
            """
        ),
        {"pattern": BENCH_EMAIL, "rooms": rooms},
    )
    conn.execute(
        text(
            """
            WITH u AS (
                SELECT id, row_number() OVER (ORDER BY id) AS n FROM users WHERE email LIKE :pattern
            )
            INSERT INTO room_participants (room_id, user_id)
            SELECT 'B' || upper(substr(md5((1 + (n - 1) % :rooms)::text), 1, 7)), id
            FROM u WHERE n <= :seated
            """
        ),
        {"pattern": BENCH_EMAIL, "rooms": rooms, "seated": rooms * per_room},
    )
    for table in ("users", "musical_rooms", "room_participants"):
        conn.execute(text(f"ANALYZE {table}"))


def _walk(plan: dict):
    yield plan
    for child in plan.get("Plans", []):
        yield from _walk(child)


def explain_sql(conn: Connection, sql: str, params: dict | None = None) -> dict:
    root = conn.execute(text(f"EXPLAIN (ANALYZE, FORMAT JSON) {sql}"), params or {}).scalar_one()[0]
    nodes = list(_walk(root["Plan"]))
    return {
        "node_types": {n["Node Type"] for n in nodes},
        "indexes": {n["Index Name"] for n in nodes if "Index Name" in n},
        "execution_ms": root["Execution Time"],
    }


def explain_search(conn: Connection, term: str) -> dict:
    stmt = song_repo.search_query(term)
    sql = stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
    return explain_sql(conn, str(sql))


def sample_room(conn: Connection) -> tuple[str, int]:
    """(an active bench room id, a seated participant of it)."""
    row = conn.execute(
        text(
            """
            SELECT rp.room_id, rp.user_id FROM room_participants rp
            JOIN musical_rooms r ON r.id = rp.room_id
            WHERE r.name LIKE 'Bench room %' ORDER BY rp.room_id LIMIT 1
            """
        )
    ).one()
    return row.room_id, row.user_id


def explain_room_lookups(conn: Connection) -> dict[str, dict]:
    room_id, user_id = sample_room(conn)
    params = {"room_id": room_id, "user_id": user_id}
    return {
        "participant": explain_sql(
            conn,
            "SELECT * FROM room_participants WHERE room_id = :room_id AND user_id = :user_id",
            params,
        ),
        "room_participants": explain_sql(
            conn, "SELECT * FROM room_participants WHERE room_id = :room_id", params
        ),
        "user_rooms": explain_sql(
            conn, "SELECT * FROM room_participants WHERE user_id = :user_id", params
        ),
        "rooms_by_admin": explain_sql(
            conn, "SELECT id FROM musical_rooms WHERE admin_user_id = :user_id", params
        ),
    }


def search_budget(term: str) -> float:
    return SEARCH_P95_MS if len(term.strip()) >= 3 else SHORT_SEARCH_P95_MS


def _percentiles(samples: list[float]) -> dict:
    samples = sorted(samples)
    return {"p50_ms": statistics.median(samples), "p95_ms": samples[max(0, int(len(samples) * 0.95) - 1)]}


def time_search(session: Session, runs: int = 20) -> dict[str, dict]:
    results = {}
    for term in SEARCH_TERMS:
        samples = []
        for _ in range(runs):
            session.expunge_all()
            start = time.perf_counter()
            rows = song_repo.search(session, term)
            samples.append((time.perf_counter() - start) * 1000)
        results[term] = {"rows": len(rows), **_percentiles(samples)}
    return results


def time_joins(conn: Connection, joins: int = 100) -> dict:
    """Each join is a new user entering a different busy room; commits release a savepoint only."""
    session = Session(bind=conn, join_transaction_mode="create_savepoint")
    rooms = conn.execute(
        text("SELECT id FROM musical_rooms WHERE name LIKE 'Bench room %' ORDER BY id LIMIT :n"),
        {"n": joins},
    ).scalars().all()
    spare = conn.execute(
        text(
            """
            SELECT u.id FROM users u WHERE u.email LIKE :pattern
            AND NOT EXISTS (SELECT 1 FROM room_participants rp WHERE rp.user_id = u.id)
            ORDER BY u.id LIMIT :n
            """
        ),
        {"pattern": BENCH_EMAIL, "n": joins},
    ).scalars().all()
    samples, sizes = [], []
    for room_id, user_id in zip(rooms, spare):
        session.expunge_all()
        start = time.perf_counter()
        out = room_service.to_room_out(room_service.join_room(session, room_id, user_id))
        samples.append((time.perf_counter() - start) * 1000)
        sizes.append(len(out.participants))
    session.close()
    return {"joins": len(samples), "room_size": max(sizes, default=0), **_percentiles(samples)}


def main(songs: int = 50_000, rooms: int = 2_000, per_room: int = 10) -> bool:
    with engine.connect() as conn:
        trans = conn.begin()
        try:
            started = time.perf_counter()
            seed_catalog(conn, songs)
            seed_rooms(conn, rooms, per_room)
            print(f"Seeded {songs:,} songs, {rooms:,} rooms x {per_room} participants "
                  f"in {time.perf_counter() - started:.1f}s")

            ok = True
            print("\nSearch plans:")
            for term in SEARCH_TERMS:
                plan = explain_search(conn, term)
                print(f"  {term!r:22} {plan['execution_ms']:7.2f} ms  {sorted(plan['indexes'])}")

            print("\nRoom lookup plans:")
            for name, plan in explain_room_lookups(conn).items():
                seq = "Seq Scan" in plan["node_types"]
                ok &= not seq
                print(f"  {name:18} {plan['execution_ms']:6.3f} ms  {sorted(plan['indexes'])}"
                      f"{'  SEQ SCAN' if seq else ''}")

            print(f"\nSearch API query (target p95 <= {SEARCH_P95_MS} ms, "
                  f"1-2 chars <= {SHORT_SEARCH_P95_MS} ms):")
            for term, t in time_search(Session(bind=conn)).items():
                ok &= t["p95_ms"] <= search_budget(term)
                print(f"  {term!r:22} {t['rows']:3} rows  p50 {t['p50_ms']:6.2f}  p95 {t['p95_ms']:6.2f} ms")

            joins = time_joins(conn)
            ok &= joins["p95_ms"] <= JOIN_P95_MS
            print(f"\nRoom join ({joins['joins']} joins, rooms of {joins['room_size']}): "
                  f"p50 {joins['p50_ms']:.2f} ms, p95 {joins['p95_ms']:.2f} ms "
                  f"(target p95 <= {JOIN_P95_MS} ms)")
            print("\nPASS" if ok else "\nFAIL")
            return ok
        finally:
            trans.rollback()


if __name__ == "__main__":
    sys.exit(0 if main(*(int(a) for a in sys.argv[1:4])) else 1)

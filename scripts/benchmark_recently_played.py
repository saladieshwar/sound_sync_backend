"""Measures the recently-played query against synthetic history.

Run from backend/: python -m scripts.benchmark_recently_played [users] [plays_per_user]

Everything happens inside one transaction that is rolled back, so the database is unchanged.
Requires at least one song (run `python -m scripts.seed` first).
"""

import statistics
import sys
import time

from sqlalchemy import Connection, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session

from app.db.session import engine
from app.repositories import library_repo

TARGET_P95_MS = 10.0
PAGE_SIZE = 20


def seed_history(conn: Connection, users: int, plays_per_user: int) -> int:
    """Inserts `users` throwaway users with `plays_per_user` plays each; returns one user's id."""
    conn.execute(
        text(
            """
            INSERT INTO users (username, email, password_hash, is_admin)
            SELECT 'bench' || g, 'bench' || g || '@bench.soundsync.dev',
                   '$2b$12$' || repeat('a', 53), false
            FROM generate_series(1, :users) AS g
            """
        ),
        {"users": users},
    )
    conn.execute(
        text(
            """
            WITH s AS (SELECT array_agg(id ORDER BY id) AS ids FROM songs),
                 u AS (SELECT id FROM users WHERE email LIKE 'bench%@bench.soundsync.dev')
            INSERT INTO recently_played (user_id, song_id, played_at)
            SELECT u.id,
                   s.ids[1 + (g % array_length(s.ids, 1))],
                   now() - make_interval(secs => g * 60 + u.id % 60)
            FROM u, s, generate_series(1, :plays) AS g
            """
        ),
        {"plays": plays_per_user},
    )
    conn.execute(text("ANALYZE recently_played"))
    conn.execute(text("ANALYZE users"))
    return conn.execute(
        text("SELECT id FROM users WHERE email LIKE 'bench%@bench.soundsync.dev' ORDER BY id LIMIT 1")
    ).scalar_one()


def _walk(plan: dict):
    yield plan
    for child in plan.get("Plans", []):
        yield from _walk(child)


def explain(conn: Connection, user_id: int, limit: int = PAGE_SIZE) -> dict:
    """EXPLAIN ANALYZE of the exact query the API runs."""
    sql = library_repo.recently_played_query(user_id, limit=limit).compile(
        dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
    )
    result = conn.execute(text(f"EXPLAIN (ANALYZE, FORMAT JSON) {sql}")).scalar_one()
    root = result[0]
    nodes = list(_walk(root["Plan"]))
    return {
        "node_types": {n["Node Type"] for n in nodes},
        "indexes": {n["Index Name"] for n in nodes if "Index Name" in n},
        "execution_ms": root["Execution Time"],
    }


def time_query(session: Session, user_id: int, runs: int = 50, limit: int = PAGE_SIZE) -> dict:
    """Wall-clock timings of library_repo.list_recently_played (includes ORM mapping)."""
    samples = []
    for _ in range(runs):
        session.expunge_all()
        start = time.perf_counter()
        rows = library_repo.list_recently_played(session, user_id, limit=limit)
        samples.append((time.perf_counter() - start) * 1000)
    samples.sort()
    return {
        "rows": len(rows),
        "p50_ms": statistics.median(samples),
        "p95_ms": samples[int(len(samples) * 0.95) - 1],
    }


def main(users: int = 1000, plays_per_user: int = 200) -> None:
    with engine.connect() as conn:
        trans = conn.begin()
        try:
            started = time.perf_counter()
            user_id = seed_history(conn, users, plays_per_user)
            print(f"Seeded {users * plays_per_user:,} plays for {users:,} users "
                  f"in {time.perf_counter() - started:.1f}s")

            plan = explain(conn, user_id)
            print(f"Plan nodes: {sorted(plan['node_types'])}")
            print(f"Indexes used: {sorted(plan['indexes'])}")
            print(f"DB execution time: {plan['execution_ms']:.3f} ms")

            session = Session(bind=conn)
            timings = time_query(session, user_id)
            print(f"API query ({timings['rows']} rows): p50 {timings['p50_ms']:.2f} ms, "
                  f"p95 {timings['p95_ms']:.2f} ms (target p95 <= {TARGET_P95_MS} ms)")
            sorts = any("Sort" in node for node in plan["node_types"])
            print("PASS" if timings["p95_ms"] <= TARGET_P95_MS and not sorts else "FAIL")
        finally:
            trans.rollback()


if __name__ == "__main__":
    main(*(int(a) for a in sys.argv[1:3]))

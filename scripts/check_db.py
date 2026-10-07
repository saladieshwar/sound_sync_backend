"""Checks that a database is ready for SoundSync and QA. Run from backend/: python -m scripts.check_db

Read-only. Prints one OK/FAIL line per check and exits with 1 if anything failed:
connection, migration at head, pg_trgm, all tables, seed accounts, seed catalog, seed media files.
See docs/db_runbook.md.
"""

import sys
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, select, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.base import Base
from app.db.session import SessionLocal
from app.models import Song, User
from scripts.seed import SONGS, USERS, audio_url_for, cover_url_for

BACKEND_DIR = Path(__file__).resolve().parent.parent


def head_revision() -> str:
    return ScriptDirectory.from_config(Config(str(BACKEND_DIR / "alembic.ini"))).get_current_head()


def _media_path(url: str) -> Path:
    return Path(settings.MEDIA_ROOT) / url.removeprefix(settings.MEDIA_URL_PREFIX).lstrip("/")


def run_checks(db: Session) -> list[tuple[str, bool, str]]:
    """Returns (check, passed, detail) rows."""
    results = []

    current = db.execute(text("SELECT version_num FROM alembic_version")).scalar()
    head = head_revision()
    results.append(("migration at head", current == head, f"current {current}, head {head}"))

    has_trgm = db.execute(text("SELECT 1 FROM pg_extension WHERE extname = 'pg_trgm'")).scalar()
    results.append(("pg_trgm extension", bool(has_trgm), "installed" if has_trgm else "missing"))

    existing = set(inspect(db.connection()).get_table_names())
    missing_tables = sorted(set(Base.metadata.tables) - existing)
    results.append(
        ("tables", not missing_tables, f"missing {missing_tables}" if missing_tables else f"{len(Base.metadata.tables)} present")
    )

    users = {u.email: u for u in db.scalars(select(User).where(User.email.in_([u["email"] for u in USERS])))}
    bad_users = [
        u["email"] for u in USERS if u["email"] not in users or users[u["email"]].is_admin != u["is_admin"]
    ]
    results.append(
        ("seed accounts", not bad_users, f"missing or wrong role: {bad_users}" if bad_users else f"{len(USERS)} present")
    )

    songs = {(s.title, s.artist): s for s in db.scalars(select(Song))}
    bad_songs = []
    for s in SONGS:
        song = songs.get((s["title"], s["artist"]))
        expected = {**s, "audio_url": audio_url_for(s["title"]), "cover_url": cover_url_for(s["album"])}
        if song is None or any(getattr(song, k) != v for k, v in expected.items()):
            bad_songs.append(s["title"])
    results.append(
        ("seed catalog", not bad_songs, f"missing or changed: {bad_songs}" if bad_songs else f"{len(SONGS)} songs match")
    )

    missing_files = sorted(
        {url for s in SONGS for url in (audio_url_for(s["title"]), cover_url_for(s["album"]))
         if not _media_path(url).is_file()}
    )
    results.append(
        ("seed media files", not missing_files, f"missing {missing_files}" if missing_files else f"present under {settings.MEDIA_ROOT}")
    )
    return results


def main() -> int:
    try:
        with SessionLocal() as db:
            results = run_checks(db)
    except Exception as exc:
        print(f"FAIL  database connection: {type(exc).__name__}: {exc}".splitlines()[0])
        return 1
    print("OK    database connection")
    for name, passed, detail in results:
        print(f"{'OK  ' if passed else 'FAIL'}  {name}: {detail}")
    failed = [name for name, passed, _ in results if not passed]
    if failed:
        print("Fix: python -m scripts.seed (seed rows/files) or alembic upgrade head (schema). See docs/db_runbook.md.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

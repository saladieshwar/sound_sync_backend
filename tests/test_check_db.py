"""DB runbook check (scripts/check_db.py) inside a rolled-back transaction."""

from sqlalchemy import select

from app.core.security import hash_password
from app.models import User
from scripts.check_db import run_checks
from scripts.seed import USERS as SEED_USERS


def _seed_users(db):
    for u in SEED_USERS:
        user = db.scalars(select(User).where(User.email == u["email"])).first()
        if user is None:
            db.add(User(username=u["username"], email=u["email"], password_hash=hash_password(u["password"]), is_admin=u["is_admin"]))
        else:
            user.is_admin = u["is_admin"]
    db.flush()


def _results(db) -> dict[str, bool]:
    return {name: passed for name, passed, _ in run_checks(db)}


def test_check_db_passes_on_a_migrated_seeded_database(db, catalog):
    _seed_users(db)
    results = _results(db)
    results.pop("seed media files")
    assert results == {
        "migration at head": True,
        "pg_trgm extension": True,
        "tables": True,
        "seed accounts": True,
        "seed catalog": True,
    }


def test_check_db_detects_missing_or_changed_seed_rows(db, catalog):
    _seed_users(db)
    db.delete(catalog["Grey Rain"])
    db.scalars(select(User).where(User.email == "admin@soundsync.dev")).one().is_admin = False
    db.flush()
    results = _results(db)
    assert results["seed catalog"] is False
    assert results["seed accounts"] is False

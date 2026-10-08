"""Phase 8 DATA: final schema and store verification.

Every foreign key's delete rule is the same in the live database, the models and
docs/qa/data_checklist.md, every foreign key is indexed, and each rule is proven by deleting real
rows with plain SQL (so the database enforces it, not the ORM). Everything is rolled back.
"""

import re
import uuid
from pathlib import Path

from sqlalchemy import delete, func, select, text

from app.core.security import hash_password
from app.db.base import Base
from app.models import LikedSong, MusicalRoom, RecentlyPlayed, RoomParticipant, Song, User

CHECKLIST = Path(__file__).resolve().parent.parent / "docs" / "qa" / "data_checklist.md"
PG_RULES = {"a": "NO ACTION", "r": "RESTRICT", "c": "CASCADE", "n": "SET NULL", "d": "SET DEFAULT"}
PASSWORD_HASH = hash_password("integrity-pass")

FOREIGN_KEYS_SQL = """
SELECT cl.relname, att.attname, ref.relname, con.confdeltype
FROM pg_constraint con
JOIN pg_class cl ON cl.oid = con.conrelid
JOIN pg_class ref ON ref.oid = con.confrelid
JOIN pg_attribute att ON att.attrelid = con.conrelid AND att.attnum = con.conkey[1]
WHERE con.contype = 'f' AND cl.relnamespace = 'public'::regnamespace
"""

# First column of every index (including primary keys) per table.
LEADING_INDEX_COLUMNS_SQL = """
SELECT cl.relname, att.attname
FROM pg_index ix
JOIN pg_class cl ON cl.oid = ix.indrelid
JOIN pg_attribute att ON att.attrelid = ix.indrelid AND att.attnum = ix.indkey[0]
WHERE cl.relnamespace = 'public'::regnamespace
"""


def _documented_rules() -> dict[tuple[str, str, str], str]:
    rows = re.findall(
        r"^\| `(\w+)\.(\w+)` \| `(\w+)\.id` \| (CASCADE|SET NULL|NO ACTION|RESTRICT) \|",
        CHECKLIST.read_text(encoding="utf-8-sig"),
        re.MULTILINE,
    )
    return {(table, column, ref): rule for table, column, ref, rule in rows}


def test_delete_rules_match_in_database_models_and_checklist(db):
    in_db = {(t, c, r): PG_RULES[rule] for t, c, r, rule in db.execute(text(FOREIGN_KEYS_SQL))}
    in_models = {
        (fk.parent.table.name, fk.parent.name, fk.column.table.name): (fk.ondelete or "NO ACTION").upper()
        for table in Base.metadata.tables.values()
        for fk in table.foreign_keys
    }
    assert in_db == in_models
    assert _documented_rules() == in_db


def test_every_foreign_key_is_indexed_so_deletes_never_scan(db):
    indexed = {tuple(row) for row in db.execute(text(LEADING_INDEX_COLUMNS_SQL))}
    for table, column, _ref, _rule in db.execute(text(FOREIGN_KEYS_SQL)):
        assert (table, column) in indexed, f"{table}.{column} has no index starting with it"


def _user(db, name: str) -> User:
    user = User(username=name, email=f"{name}_{uuid.uuid4().hex[:8]}@soundsync.dev", password_hash=PASSWORD_HASH)
    db.add(user)
    db.flush()
    return user


def _song(db, title: str) -> Song:
    song = Song(
        title=f"{title} {uuid.uuid4().hex[:6]}",
        artist="DATA",
        album=None,
        category="test",
        duration_seconds=60,
        audio_url="/media/audio/integrity.wav",
        cover_url=None,
    )
    db.add(song)
    db.flush()
    return song


def _room(db, admin: User, controller: User, members: list[User], song: Song | None = None) -> str:
    room = MusicalRoom(
        id=uuid.uuid4().hex[:8].upper(),
        name="Integrity",
        admin_user_id=admin.id,
        controller_user_id=controller.id,
        current_song_id=song.id if song else None,
        is_playing=song is not None,
    )
    room.participants = [RoomParticipant(user_id=m.id) for m in members]
    db.add(room)
    db.flush()
    return room.id


def _library(db, user: User, song: Song) -> None:
    db.add_all([LikedSong(user_id=user.id, song_id=song.id), RecentlyPlayed(user_id=user.id, song_id=song.id)])
    db.flush()


def _count(db, model, **where) -> int:
    return db.scalar(select(func.count()).select_from(model).filter_by(**where))


def test_deleting_a_user_removes_their_data_and_the_rooms_they_own(db):
    owner, guest = _user(db, "owner"), _user(db, "guest")
    song = _song(db, "Shared")
    _library(db, owner, song)
    _library(db, guest, song)
    owned = _room(db, admin=owner, controller=guest, members=[owner, guest], song=song)
    joined = _room(db, admin=guest, controller=owner, members=[guest, owner])

    db.execute(delete(User).where(User.id == owner.id))
    db.expire_all()

    assert _count(db, LikedSong, user_id=owner.id) == _count(db, RecentlyPlayed, user_id=owner.id) == 0
    assert _count(db, LikedSong, user_id=guest.id) == _count(db, RecentlyPlayed, user_id=guest.id) == 1
    assert db.get(MusicalRoom, owned) is None
    assert _count(db, RoomParticipant, room_id=owned) == 0
    room = db.get(MusicalRoom, joined)
    assert room.controller_user_id is None
    assert [p.user_id for p in room.participants] == [guest.id]
    assert db.get(Song, song.id) is not None


def test_deleting_a_song_removes_library_rows_and_clears_rooms(db):
    user = _user(db, "listener")
    doomed, kept = _song(db, "Doomed"), _song(db, "Kept")
    _library(db, user, doomed)
    _library(db, user, kept)
    room_id = _room(db, admin=user, controller=user, members=[user], song=doomed)

    db.execute(delete(Song).where(Song.id == doomed.id))
    db.expire_all()

    assert _count(db, LikedSong, song_id=doomed.id) == _count(db, RecentlyPlayed, song_id=doomed.id) == 0
    assert _count(db, LikedSong, song_id=kept.id) == _count(db, RecentlyPlayed, song_id=kept.id) == 1
    room = db.get(MusicalRoom, room_id)
    assert room is not None and room.current_song_id is None
    assert db.get(User, user.id) is not None


def test_deleting_a_room_removes_only_its_participants(db):
    alice, bob = _user(db, "alice"), _user(db, "bob")
    gone = _room(db, admin=alice, controller=alice, members=[alice, bob])
    other = _room(db, admin=bob, controller=bob, members=[bob, alice])

    db.execute(delete(MusicalRoom).where(MusicalRoom.id == gone))
    db.expire_all()

    assert _count(db, RoomParticipant, room_id=gone) == 0
    assert _count(db, RoomParticipant, room_id=other) == 2
    assert db.get(User, alice.id) is not None and db.get(User, bob.id) is not None

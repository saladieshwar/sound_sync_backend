# DATA Checklist: Final Schema and Store Verification (Phase 8)

Handbook Phase 8, DATA: "Final schema/store verification. Deliverable: cascade deletes + backup check. Done when: DATA checklist signed."

Every item below was checked on 2026-10-07 against the final code (migration `0005`, PostgreSQL 18). `tests/test_data_integrity.py` reads the foreign-key table on this page, so if the database, the models or this page ever disagree, `pytest` fails.

## Foreign keys and delete rules

What happens to related rows when a user, song or room is deleted. The database enforces every rule (the tests delete with plain SQL, not through the ORM).

| Column | References | On delete | Effect | Proven by |
| --- | --- | --- | --- | --- |
| `liked_songs.user_id` | `users.id` | CASCADE | A deleted user's likes are removed | `test_data_integrity::test_deleting_a_user_removes_their_data_and_the_rooms_they_own` |
| `liked_songs.song_id` | `songs.id` | CASCADE | A deleted song disappears from every Liked Songs list | `test_data_integrity::test_deleting_a_song_removes_library_rows_and_clears_rooms`, `test_admin::test_admin_delete_removes_song_library_rows_and_files` |
| `recently_played.user_id` | `users.id` | CASCADE | A deleted user's play history is removed | `test_data_integrity::test_deleting_a_user_removes_their_data_and_the_rooms_they_own` |
| `recently_played.song_id` | `songs.id` | CASCADE | A deleted song disappears from every Recently Played list | `test_data_integrity::test_deleting_a_song_removes_library_rows_and_clears_rooms`, `test_library::test_deleting_song_removes_it_from_libraries` |
| `musical_rooms.admin_user_id` | `users.id` | CASCADE | Rooms a deleted user created are removed (with their participants) | `test_data_integrity::test_deleting_a_user_removes_their_data_and_the_rooms_they_own` |
| `musical_rooms.controller_user_id` | `users.id` | SET NULL | A room whose controller is deleted keeps going; its admin can take control back | `test_data_integrity::test_deleting_a_user_removes_their_data_and_the_rooms_they_own` |
| `musical_rooms.current_song_id` | `songs.id` | SET NULL | A room playing a deleted song is left with no song (the admin delete also stops it and tells the clients) | `test_data_integrity::test_deleting_a_song_removes_library_rows_and_clears_rooms`, `test_room_sync::test_admin_deleting_the_playing_song_stops_the_room_for_everyone` |
| `room_participants.room_id` | `musical_rooms.id` | CASCADE | Deleting a room removes its participant rows, and only those | `test_data_integrity::test_deleting_a_room_removes_only_its_participants`, `test_rooms::test_deleting_room_cascades_to_participants` |
| `room_participants.user_id` | `users.id` | CASCADE | A deleted user leaves every room they had joined | `test_data_integrity::test_deleting_a_user_removes_their_data_and_the_rooms_they_own` |

Users and songs themselves are never deleted by a cascade: no foreign key points from them to anything else.

## Checklist

| # | Check | How | Result | Status |
| --- | --- | --- | --- | --- |
| 1 | Schema is at the final migration with no drift | `alembic current` = `0005 (head)`; `alembic check` = no new upgrade operations | `0005`, no drift (dev database and restored copy) | Done |
| 2 | Delete rules are identical in the database, the models and this page | `test_delete_rules_match_in_database_models_and_checklist` (reads `pg_constraint`) | 9 foreign keys, all match | Done |
| 3 | Every delete rule works on real rows | The three `test_deleting_…` tests above, plus the existing admin, library and room tests | Pass | Done |
| 4 | Cascades never scan a whole table | `test_every_foreign_key_is_indexed_so_deletes_never_scan`: every foreign-key column is the first column of an index | 9 of 9 indexed | Done |
| 5 | Data rules enforced by the database | Unique lower-case email, bcrypt-only `password_hash` (`ck_users_*`), composite primary keys on `liked_songs` and `room_participants`, `room_status` enum | `tests/test_auth.py` (AUTH-02, AUTH-07), `test_library.py` (LIB-02), `test_rooms.py` | Done |
| 6 | Deleting a song through the app also cleans up outside the database | `DELETE /admin/songs/{id}` removes the audio and cover files (unless another song uses them) and stops active rooms playing it | `test_admin_delete_removes_song_library_rows_and_files`, `test_admin_delete_keeps_files_other_songs_still_use`, `test_admin_deleting_the_playing_song_stops_the_room_for_everyone` | Done |
| 7 | Seed fixtures are complete | `python -m scripts.check_db` | 7 × OK | Done |
| 8 | Backup restores completely (backup check) | `python -m scripts.restore_check` onto a brand-new PostgreSQL 18 server set up only with `scripts/setup_db.sql` ([`db_runbook.md`](../db_runbook.md) section 8) | See "Backup check" below: PASS | Done |
| 9 | The app works on the restored copy | Full `pytest` with `DATABASE_URL` and `TEST_DATABASE_URL` pointing at the copy | 226 passed | Done |

## Backup check (2026-10-07, final schema)

A throwaway PostgreSQL 18 server (port 5499, deleted afterwards) was created, `scripts/setup_db.sql` made the `soundsync` role (no superuser, no create-database rights) and database, and then:

```powershell
python -m scripts.restore_check postgresql+psycopg://soundsync@127.0.0.1:5499/soundsync
```

| Step | Result |
| --- | --- |
| Backup | `pg_dump` custom-format archive, 76 entries; media zip round trip: 16 files identical |
| Restore into the empty database | 7 tables, 52 rows, data checksums equal; 23 indexes, 51 constraints, 3 sequences, 2 extensions equal; migration `0005`; `check_db` all OK; `alembic check` no drift |
| Restore again over the copy with `--clean` | Identical again |
| Source database | Unchanged |
| Overall | 20 × OK, **PASS** |
| `pytest` on the restored copy | 226 passed |

## Sign-off

| Lead | Team | Signed | Date | Notes |
| --- | --- | --- | --- | --- |
| Eshwar (saladieshwar) | DATA | Yes | 2026-10-07 | Cascade deletes verified in the database, models and docs; backup check PASS on the final schema |
| Eshwar (saladieshwar) | QA | Yes | 2026-10-07 | Evidence reproduced with `pytest` and `restore_check` |

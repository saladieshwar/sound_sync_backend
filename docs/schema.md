# Schema Note (DATA → BE)

Source of truth: `alembic/versions/` (ORM mirror in `app/models/`). Current migration: `0005`.

| Migration | Change |
| --- | --- |
| `0001` | Initial schema (all tables below) |
| `0002` | `users`: `ck_users_email_lowercase` (`email = lower(email)`) and `ck_users_password_hash_bcrypt` (`password_hash ~ '^\$2[aby]\$'`) |
| `0003` | Catalog/library indexes: `pg_trgm` extension; GIN trigram indexes `ix_songs_{title,artist,album}_trgm` (substring search); `ix_songs_category_lower` on `lower(category)` (category filter); `ix_liked_songs_user_liked_at`, `ix_liked_songs_song_id`, `ix_recently_played_song_id`. `liked_at` / `played_at` default to `clock_timestamp()` so rows written in one transaction keep their real order |
| `0004` | `recently_played`: replaces `ix_recently_played_user_played_at` with `ix_recently_played_user_played_at_id` (`user_id`, `played_at DESC`, `id DESC`), matching the history query's `ORDER BY` so the page is read straight off the index with no sort step |
| `0005` | `songs`: stored generated column `search_text` = `lower(title ‖ chr(31) ‖ artist ‖ chr(31) ‖ coalesce(album, ''))` with one GIN trigram index `ix_songs_search_trgm`, replacing the three per-column trigram indexes. `musical_rooms`: indexes on `admin_user_id`, `controller_user_id`, `current_song_id` (deleting a user/song no longer scans every room) and partial `ix_musical_rooms_active_created_at` (`created_at DESC` where `status = 'active'`, the admin room list); `created_at` defaults to `clock_timestamp()` |

| Table | Key columns | Notes |
| --- | --- | --- |
| `users` | `id`, `username`, `email` (unique, lower-case), `password_hash`, `is_admin`, `created_at` | DB rejects duplicate emails, non-lower-case emails, and any `password_hash` that is not a bcrypt hash |
| `songs` | `id`, `title`, `artist`, `album`, `category`, `duration_seconds`, `audio_url`, `cover_url`, `search_text` (generated, not in the API) | B-tree indexes on title/artist/album/category; trigram index on `search_text` for search; `lower(category)` index |
| `liked_songs` | PK (`user_id`, `song_id`), `liked_at` | index (`user_id`, `liked_at`) for "newest first"; index `song_id`; cascades on user/song delete |
| `recently_played` | `id`, `user_id`, `song_id`, `played_at` | full play history (a replay adds a new row); index (`user_id`, `played_at DESC`, `id DESC`); index `song_id`; cascades on user/song delete |
| `musical_rooms` | `id` (8-char Room ID), `name`, `admin_user_id`, `controller_user_id`, `current_song_id`, `is_playing`, `position_seconds`, `state_updated_at`, `status` | `status` enum: `active` / `closed`; deleting the admin user deletes the room (CASCADE); deleting the controller or current song sets them to NULL; indexes on all three foreign keys and on active rooms by `created_at DESC` |
| `room_participants` | PK (`room_id`, `user_id`), `joined_at` | row deleted on leave; cascades on room delete and user delete; index `user_id` |

Repository mapping (BE): `user_repo` → `users`; `song_repo` → `songs`; `library_repo` → `liked_songs`, `recently_played`; `room_repo` → `musical_rooms`, `room_participants`.

## Catalog query rules (Phase 3)

| Endpoint | Query | Order |
| --- | --- | --- |
| `GET /songs/search?q=` | case-insensitive substring of title, artist, or album (`search_text LIKE lower(pattern)`; a term never matches across two fields); `q` trimmed, 1–100 chars; `%`, `_`, `\` match literally | title, id (max 50) |
| `GET /songs/category/{name}` | `lower(category) = lower(name)`; unknown category → `[]` | title, id |
| `GET /songs/albums` | grouped by album, with `song_count` | album |
| `GET /users/me/liked-songs` | current user only | `liked_at` desc, `song_id` desc |
| `GET /users/me/recently-played?limit=` | current user only; 1–100 (default 20) | `played_at` desc, `id` desc |

Seed catalog (`python -m scripts.seed`, idempotent): 8 songs, 4 albums × 2 songs, 4 categories (`love`, `melody`, `motivation`, `sad`) × 2 songs. Album covers are generated as SVG under `MEDIA_ROOT/covers/` (e.g. `/media/covers/calm-skies.svg`). Audio is generated as WAV (8 kHz, 8-bit mono, ~8 KB/s) under `MEDIA_ROOT/audio/` (e.g. `/media/audio/rise-up.wav`); each file is exactly the song's `duration_seconds` long. `/media` supports HTTP range requests (206), which browsers need for seeking.

## Recently-played performance (Phase 4)

Target: the history page query (`GET /users/me/recently-played`, 20 rows) runs in **p95 ≤ 10 ms** and the plan uses `ix_recently_played_user_played_at_id` with **no sort node**.

Measure with `python -m scripts.benchmark_recently_played [users] [plays_per_user]` (inserts synthetic history inside a rolled-back transaction). Result on 2026-10-03, PostgreSQL 18, 1,000 users × 200 plays (200,000 rows):

| Index | Plan | DB execution | API query p50 / p95 |
| --- | --- | --- | --- |
| `0003` (`user_id`, `played_at`) | Index Scan + **Incremental Sort** | 0.13 ms | 0.89 / 1.95 ms |
| `0004` (`user_id`, `played_at DESC`, `id DESC`) | Index Scan only (no sort) | 0.46 ms | 0.87 / 1.67 ms |

Both are within target at this size; `0004` removes the sort step, so the cost stays flat as one user's history grows and tied `played_at` values cannot force a sort. `tests/test_playback.py::test_recently_played_query_uses_index_without_sort` guards the plan shape.

## Search and room-join performance (Phase 6)

Budgets (p95, through the same repository/service code the API runs): search with 3+ characters **≤ 25 ms**, with 1–2 characters **≤ 100 ms**, room join **≤ 50 ms**; room participant/membership lookups must be index scans.

Measure with `python -m scripts.benchmark_catalog_rooms [songs] [rooms] [participants_per_room]` (synthetic data inside a rolled-back transaction). Result on 2026-10-07, PostgreSQL 18, 50,000 songs, 2,000 active rooms × 10 participants:

| Query | Before `0005` | After `0005` |
| --- | --- | --- |
| Search `c4ca4` / `artist 1234` / `album 0042` (p95) | 0.3–4 ms in the DB with a settled index, but the planner skipped the three per-column indexes for a seq scan whenever their pending lists were not merged (250–500 ms) | **4.0 / 7.8 / 7.4 ms**, one `ix_songs_search_trgm` probe |
| Search `lo` (2 letters, p95) | 233 ms (per-row `ILIKE` on three columns) | **51 ms** (plain `LIKE` on one pre-lowered column) |
| Search `a` (p95) | 0.3 ms (`ix_songs_title` ordered scan) | 4.3 ms (same plan) |
| Room join, rooms of 11 (p50 / p95) | 18.7 / 22.4 ms | **11.3 / 15.2 ms** |
| Participant by (room, user) / by room / by user | index | index (0.04–0.12 ms) |
| Rooms by admin (user delete cascade) | **seq scan** of `musical_rooms` | `ix_musical_rooms_admin_user_id` (0.06 ms) |

`tests/test_performance.py` guards the plan shapes (trigram index for 3+ characters, no seq scans for room lookups) and the join budget on a smaller seed. Load-level budgets are in `docs/sync_tuning.md` → "Performance budgets".

Local bring-up: see "Local database bring-up" in `backend/README.md` (`scripts/setup_db.sql` → `alembic upgrade head` → `python -m scripts.seed`).

## Musical Room rules (Phase 5)

Admin-leave rule: when the room admin leaves, the room is set to `closed`, `is_playing` is cleared, and all participant rows are removed. When a non-admin controller leaves, control returns to the admin. Either way the leaver's `room_participants` row is deleted in the same transaction as the room update.

Concurrency: leave, transfer-access, and every playback event lock the `musical_rooms` row (`SELECT … FOR UPDATE`), so a controller check and the state write it guards are atomic — a transfer that commits first always wins over a playback event from the old controller.

Playback state written by RT (`room_service.apply_playback_event`): `song_change` sets `current_song_id` and `is_playing = true`; `play` / `pause` set `is_playing`; `seek` keeps it. `position_seconds` is clamped to `[0, duration_seconds]` and `state_updated_at` is set to the write time. Migrations: the room tables come from `0001`; Phase 5 needed no new migration; Phase 6 adds the room indexes in `0005`.

Evidence: `tests/test_rooms.py` (`test_leave_removes_participant_row`, `test_admin_leaving_closes_room_and_clears_participants`, `test_deleting_room_cascades_to_participants`, `test_controller_leaving_returns_control_to_admin`).

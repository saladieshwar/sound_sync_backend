# Schema Note (DATA → BE)

Source of truth: `alembic/versions/` (ORM mirror in `app/models/`). Current migration: `0003`.

| Migration | Change |
| --- | --- |
| `0001` | Initial schema (all tables below) |
| `0002` | `users`: `ck_users_email_lowercase` (`email = lower(email)`) and `ck_users_password_hash_bcrypt` (`password_hash ~ '^\$2[aby]\$'`) |
| `0003` | Catalog/library indexes: `pg_trgm` extension; GIN trigram indexes `ix_songs_{title,artist,album}_trgm` (substring search); `ix_songs_category_lower` on `lower(category)` (category filter); `ix_liked_songs_user_liked_at`, `ix_liked_songs_song_id`, `ix_recently_played_song_id`. `liked_at` / `played_at` default to `clock_timestamp()` so rows written in one transaction keep their real order |

| Table | Key columns | Notes |
| --- | --- | --- |
| `users` | `id`, `username`, `email` (unique, lower-case), `password_hash`, `is_admin`, `created_at` | DB rejects duplicate emails, non-lower-case emails, and any `password_hash` that is not a bcrypt hash |
| `songs` | `id`, `title`, `artist`, `album`, `category`, `duration_seconds`, `audio_url`, `cover_url` | B-tree indexes on title/artist/album/category; trigram indexes for search; `lower(category)` index |
| `liked_songs` | PK (`user_id`, `song_id`), `liked_at` | index (`user_id`, `liked_at`) for "newest first"; index `song_id`; cascades on user/song delete |
| `recently_played` | `id`, `user_id`, `song_id`, `played_at` | full play history (a replay adds a new row); index (`user_id`, `played_at`); index `song_id`; cascades on user/song delete |
| `musical_rooms` | `id` (8-char Room ID), `name`, `admin_user_id`, `controller_user_id`, `current_song_id`, `is_playing`, `position_seconds`, `state_updated_at`, `status` | `status` enum: `active` / `closed` |
| `room_participants` | PK (`room_id`, `user_id`), `joined_at` | row deleted on leave; cascades on room delete |

Repository mapping (BE): `user_repo` → `users`; `song_repo` → `songs`; `library_repo` → `liked_songs`, `recently_played`; `room_repo` → `musical_rooms`, `room_participants`.

## Catalog query rules (Phase 3)

| Endpoint | Query | Order |
| --- | --- | --- |
| `GET /songs/search?q=` | case-insensitive substring of title, artist, or album; `q` trimmed, 1–100 chars; `%`, `_`, `\` match literally | title, id (max 50) |
| `GET /songs/category/{name}` | `lower(category) = lower(name)`; unknown category → `[]` | title, id |
| `GET /songs/albums` | grouped by album, with `song_count` | album |
| `GET /users/me/liked-songs` | current user only | `liked_at` desc, `song_id` desc |
| `GET /users/me/recently-played?limit=` | current user only; 1–100 (default 20) | `played_at` desc, `id` desc |

Seed catalog (`python -m scripts.seed`, idempotent): 8 songs, 4 albums × 2 songs, 4 categories (`love`, `melody`, `motivation`, `sad`) × 2 songs. Album covers are generated as SVG under `MEDIA_ROOT/covers/` (e.g. `/media/covers/calm-skies.svg`). Seed audio files (`/media/audio/sample-N.mp3`) are supplied in Phase 4.

Local bring-up: see "Local database bring-up" in `backend/README.md` (`scripts/setup_db.sql` → `alembic upgrade head` → `python -m scripts.seed`).

Admin-leave rule: when the room admin leaves, the room is set to `closed` and all participant rows are removed. When a non-admin controller leaves, control returns to the admin.

# Schema Note (DATA → BE)

Source of truth: `alembic/versions/` (ORM mirror in `app/models/`). Current migration: `0002`.

| Migration | Change |
| --- | --- |
| `0001` | Initial schema (all tables below) |
| `0002` | `users`: `ck_users_email_lowercase` (`email = lower(email)`) and `ck_users_password_hash_bcrypt` (`password_hash ~ '^\$2[aby]\$'`) |

| Table | Key columns | Notes |
| --- | --- | --- |
| `users` | `id`, `username`, `email` (unique, lower-case), `password_hash`, `is_admin`, `created_at` | DB rejects duplicate emails, non-lower-case emails, and any `password_hash` that is not a bcrypt hash |
| `songs` | `id`, `title`, `artist`, `album`, `category`, `duration_seconds`, `audio_url`, `cover_url` | indexes on title/artist/album/category |
| `liked_songs` | PK (`user_id`, `song_id`), `liked_at` | cascades on user/song delete |
| `recently_played` | `id`, `user_id`, `song_id`, `played_at` | index (`user_id`, `played_at`) |
| `musical_rooms` | `id` (8-char Room ID), `name`, `admin_user_id`, `controller_user_id`, `current_song_id`, `is_playing`, `position_seconds`, `state_updated_at`, `status` | `status` enum: `active` / `closed` |
| `room_participants` | PK (`room_id`, `user_id`), `joined_at` | row deleted on leave; cascades on room delete |

Repository mapping (BE): `user_repo` → `users`; `song_repo` → `songs`; `library_repo` → `liked_songs`, `recently_played`; `room_repo` → `musical_rooms`, `room_participants`.

Local bring-up: see "Local database bring-up" in `backend/README.md` (`scripts/setup_db.sql` → `alembic upgrade head` → `python -m scripts.seed`).

Admin-leave rule: when the room admin leaves, the room is set to `closed` and all participant rows are removed. When a non-admin controller leaves, control returns to the admin.

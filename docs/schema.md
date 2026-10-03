# Schema Note (DATA → BE)

Source of truth: `alembic/versions/` (ORM mirror in `app/models/`). Migration identity: `0001`.

| Table | Key columns | Notes |
| --- | --- | --- |
| `users` | `id`, `username`, `email` (unique), `password_hash`, `is_admin`, `created_at` | bcrypt hash only, never plaintext |
| `songs` | `id`, `title`, `artist`, `album`, `category`, `duration_seconds`, `audio_url`, `cover_url` | indexes on title/artist/album/category |
| `liked_songs` | PK (`user_id`, `song_id`), `liked_at` | cascades on user/song delete |
| `recently_played` | `id`, `user_id`, `song_id`, `played_at` | index (`user_id`, `played_at`) |
| `musical_rooms` | `id` (8-char Room ID), `name`, `admin_user_id`, `controller_user_id`, `current_song_id`, `is_playing`, `position_seconds`, `state_updated_at`, `status` | `status` enum: `active` / `closed` |
| `room_participants` | PK (`room_id`, `user_id`), `joined_at` | row deleted on leave; cascades on room delete |

Admin-leave rule: when the room admin leaves, the room is set to `closed` and all participant rows are removed. When a non-admin controller leaves, control returns to the admin.

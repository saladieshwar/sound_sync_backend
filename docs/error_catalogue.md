# Error Catalogue (BE → QA, FE)

Source of truth: `app/core/errors.py`. Every error response has this shape:

```json
{ "error": { "code": "EMAIL_ALREADY_REGISTERED", "message": "An account with this email already exists", "details": {} } }
```

`message` is safe to show to users. `details` carries machine-readable context (e.g. field errors).

Every code below is checked against `app/core/errors.py` and has at least one passing test: see [`qa/error_crosscheck.md`](qa/error_crosscheck.md) (kept in sync by `tests/test_docs.py`).

## Codes

| Code | HTTP | When |
| --- | --- | --- |
| `VALIDATION_ERROR` | 422 | Request body/query fails validation. `details.errors[]` = `{ loc, msg, type }` |
| `EMAIL_ALREADY_REGISTERED` | 409 | Register with an email that exists (case-insensitive), including concurrent duplicates |
| `INVALID_CREDENTIALS` | 401 | Login with unknown email or wrong password (identical response for both) |
| `INVALID_TOKEN` | 401 | Protected route with missing, malformed, expired, wrongly signed, or `exp`-less token, or token for a deleted user |
| `ADMIN_REQUIRED` | 403 | Non-admin calls `/admin/*` |
| `SONG_NOT_FOUND` | 404 | Unknown song id |
| `ROOM_NOT_FOUND` | 404 | Unknown room id |
| `ROOM_CLOSED` | 410 | Room exists but is closed |
| `NOT_ROOM_PARTICIPANT` | 403 | Room action by a user who has not joined |
| `NOT_ROOM_CONTROLLER` | 403 | Transfer-access by someone who is neither admin nor controller; over WebSocket, a playback event from a non-controller |
| `NO_CURRENT_SONG` | 409 | Over WebSocket: `play` / `pause` / `seek` before the room has a song |
| `UNSUPPORTED_FILE_TYPE` | 415 | Admin upload with an audio or cover file whose extension is not allowed. `details` = `{ field, allowed }` |
| `FILE_TOO_LARGE` | 413 | Admin upload over the size limit (audio 50 MB, cover 5 MB). `details` = `{ field, max_bytes }` |
| `NOT_FOUND` | 404 | Unknown route |
| `METHOD_NOT_ALLOWED` | 405 | Wrong HTTP method for a route |
| `HTTP_ERROR` | varies | Any other framework-level HTTP error |
| `INTERNAL_ERROR` | 500 | Unhandled server error; internal details are never included |

Health endpoints are for monitoring and do not use the error shape: `GET /health` is always `200 {"status": "ok"}` while the process runs; `GET /ready` is `200 {"status": "ready", "database": "up"}` or `503 {"status": "unavailable", "database": "down"}`.

WebSocket errors are not HTTP responses: they arrive as `{ "type": "error", "payload": { "code": … } }` with the codes `INVALID_MESSAGE`, `INVALID_PAYLOAD`, `EVENT_NOT_ALLOWED`, `NOT_ROOM_CONTROLLER`, `NO_CURRENT_SONG`, `SONG_NOT_FOUND`, `ROOM_CLOSED` (meanings in `docs/websocket_contract.md` → "Error codes").

## Auth examples (Phase 2)

Register:

```http
POST /auth/register
Content-Type: application/json

{ "username": "alice", "email": "alice@soundsync.dev", "password": "alice12345" }
```

- `201` → `{ "id", "username", "email", "is_admin", "created_at" }` (never `password` / `password_hash`)
- `409 EMAIL_ALREADY_REGISTERED`
- `422 VALIDATION_ERROR`, e.g. `details.errors[0]` = `{ "loc": ["body", "password"], "msg": "Value error, Password must be at most 72 bytes" }`

Validation rules: `username` 2–50 chars (trimmed); valid `email` (stored lower-case); `password` 8–72 chars and ≤ 72 UTF-8 bytes (bcrypt limit).

Login:

```http
POST /auth/login
Content-Type: application/json

{ "email": "alice@soundsync.dev", "password": "alice12345" }
```

- `200` → `{ "access_token": "<JWT>", "token_type": "bearer", "user": { ... } }`
- `401 INVALID_CREDENTIALS`

JWT: HS256, claims `sub` (user id), `iat`, `exp` (`ACCESS_TOKEN_EXPIRE_MINUTES`, default 60), `is_admin`. Send as `Authorization: Bearer <JWT>`.

Current user:

```http
GET /auth/me
Authorization: Bearer <JWT>
```

- `200` → user
- `401 INVALID_TOKEN`

In Swagger UI (`/docs`): call `/auth/login`, copy `access_token`, click **Authorize**, paste it, then call protected routes.

## Catalog & library examples (Phase 3)

Catalog reads (`/songs/*`) are public. Library routes (`/users/me/*`) require `Authorization: Bearer <JWT>`; without a valid token → `401 INVALID_TOKEN`.

| Request | Success | Errors |
| --- | --- | --- |
| `GET /songs?skip=&limit=` | `200` song list (`skip` ≥ 0, `limit` 1–200) | `422 VALIDATION_ERROR` |
| `GET /songs/search?q=rain` | `200` matching songs; no match → `[]` | `422 VALIDATION_ERROR` when `q` is missing, blank, or > 100 chars |
| `GET /songs/categories` | `200` distinct category names, sorted | — |
| `GET /songs/category/{name}` | `200` songs in that category; unknown → `[]` | — |
| `GET /songs/albums`, `GET /songs/album/{name}` | `200` | — |
| `GET /songs/{song_id}` | `200` song | `404 SONG_NOT_FOUND`; non-integer id → `422 VALIDATION_ERROR` |
| `POST /users/me/liked-songs/{song_id}` | `201` `{ song, liked_at }`; liking again returns the same like | `404 SONG_NOT_FOUND`, `401 INVALID_TOKEN` |
| `DELETE /users/me/liked-songs/{song_id}` | `204`; also `204` if the song was not liked | `401 INVALID_TOKEN` |
| `GET /users/me/liked-songs` | `200` newest first | `401 INVALID_TOKEN` |
| `POST /users/me/recently-played/{song_id}` | `201` `{ song, played_at }` | `404 SONG_NOT_FOUND`, `401 INVALID_TOKEN` |
| `GET /users/me/recently-played?limit=` | `200` play history, most recent first (`limit` 1–100, default 20) | `422 VALIDATION_ERROR`, `401 INVALID_TOKEN` |

## Profile examples

Profile routes act on the signed-in user only and require `Authorization: Bearer <JWT>`; without a valid token → `401 INVALID_TOKEN`. Every success returns the updated user (`UserOut`: `id`, `username`, `email`, `is_admin`, `full_name`, `phone`, `bio`, `avatar_url`, `created_at`).

| Request | Success | Errors |
| --- | --- | --- |
| `PATCH /users/me` `{ "username"?, "full_name"?, "phone"?, "bio"? }` | `200`; only the fields sent change; text is trimmed; a blank `full_name`, `phone` or `bio` → `null` | `422 VALIDATION_ERROR` (username blank, `null` or > 50, full name > 100, bio > 300, phone not 7–15 digits or using characters other than digits, spaces, `+ ( ) -`, or any other field such as `email` or `is_admin`) |
| `PUT /users/me/avatar` (multipart: `avatar_file`) | `200`; stored under `MEDIA_ROOT/avatars/` with a random name and served from `/media/avatars/…`; the previous picture file is deleted | `415 UNSUPPORTED_FILE_TYPE` (`.jpg .jpeg .png .webp .gif`), `413 FILE_TOO_LARGE` (`MAX_COVER_UPLOAD_BYTES`), `422 VALIDATION_ERROR` (empty file). A rejected file leaves the old picture in place and nothing new on disk |
| `DELETE /users/me/avatar` | `200` with `avatar_url: null`; the file is deleted; also `200` when there was no picture | — |

## Musical Room examples (Phase 5)

All room routes require `Authorization: Bearer <JWT>`; without a valid token → `401 INVALID_TOKEN`. Room IDs are case-insensitive in every path.

| Request | Success | Errors |
| --- | --- | --- |
| `POST /rooms` `{ "name": "Friday night" }` | `201` `RoomOut`; 8-char upper-case `id`, `join_link`, creator is admin + controller + first participant | `422 VALIDATION_ERROR` (name blank or > 100 chars) |
| `GET /rooms/{room_id}` | `200` `RoomOut` | `403 NOT_ROOM_PARTICIPANT`, `404 ROOM_NOT_FOUND`, `410 ROOM_CLOSED` |
| `POST /rooms/{room_id}/join` | `200` `RoomOut`; joining again is a no-op | `404 ROOM_NOT_FOUND`, `410 ROOM_CLOSED` |
| `POST /rooms/{room_id}/leave` | `200` `{ "message": "Left room" }` (participant row deleted; control returns to admin if the leaver was controller) or `{ "message": "Room closed" }` (admin left: room closed, all participant rows deleted) | `403 NOT_ROOM_PARTICIPANT`, `404`, `410` |
| `POST /rooms/{room_id}/transfer-access` `{ "target_user_id": 7 }` | `200` `RoomOut` with the new `controller_user_id` | `403 NOT_ROOM_CONTROLLER` (caller is neither admin nor controller), `403 NOT_ROOM_PARTICIPANT` (target has not joined), `404`, `410` |

WebSocket errors are sent as `error` events, not HTTP responses; see `docs/websocket_contract.md`.

## Admin examples (Phase 6)

All `/admin/*` routes need an admin JWT: no/invalid token → `401 INVALID_TOKEN`; non-admin → `403 ADMIN_REQUIRED`.

| Request | Success | Errors |
| --- | --- | --- |
| `POST /admin/songs` (multipart: `title`, `artist`, `album?`, `music_director?`, `category`, `duration_seconds`, `audio_file`, `cover_file?`) | `201` `SongOut`; files stored under `MEDIA_ROOT` with random names and served from `/media/audio/…`, `/media/covers/…`; text fields trimmed, blank `album` or `music_director` → `null` | `415 UNSUPPORTED_FILE_TYPE` (audio: `.mp3 .wav .ogg .oga .opus .m4a .aac .flac .webm`; cover: `.jpg .jpeg .png .webp .gif` — no SVG/HTML, since `/media` is served from the API origin), `413 FILE_TOO_LARGE`, `422 VALIDATION_ERROR` (blank title/artist/category, title, artist, album or music director > 200, category > 50, duration < 0 or > 24 h, empty file). Nothing is left on disk when an upload is rejected |
| `PATCH /admin/songs/{song_id}` `{ "title"?, "artist"?, "album"?, "music_director"?, "category"?, "duration_seconds"? }` | `200` `SongOut`; only the fields sent change; text trimmed; blank or `null` `album` / `music_director` → `null`; search sees the new details at once | `404 SONG_NOT_FOUND`, `422 VALIDATION_ERROR` (same limits as upload; `title`, `artist`, `category`, `duration_seconds` cannot be blank or `null`; any other field such as `audio_url`). A rejected edit changes nothing |
| `PUT /admin/songs/{song_id}/cover` (multipart: `cover_file`) | `200` `SongOut` with the new `cover_url`; the old cover file is deleted unless another song still uses it | `404 SONG_NOT_FOUND`, `415 UNSUPPORTED_FILE_TYPE`, `413 FILE_TOO_LARGE`, `422 VALIDATION_ERROR` (empty file). A rejected file keeps the old cover |
| `DELETE /admin/songs/{song_id}/cover` | `200` `SongOut` with `cover_url: null`; the file is deleted unless another song still uses it | `404 SONG_NOT_FOUND` |
| `DELETE /admin/songs/{song_id}` | `204`; likes and plays cascade-deleted; active rooms playing it are stopped with no current song and their clients get a `pause` with `song_id: null` (`websocket_contract.md` v1.4); its audio/cover files are removed unless another song still uses them (seed songs share album covers) | `404 SONG_NOT_FOUND` |
| `GET /admin/users?skip=&limit=` | `200` users by id (never password fields; `limit` 1–500, default 100) | `422 VALIDATION_ERROR` |
| `GET /admin/rooms` | `200` active rooms, newest first | — |

## Logging

Server logs never contain JWTs: the room WebSocket URL carries the token as `?token=`, and `app/core/log_redaction.py` rewrites it to `token=[redacted]` on the `uvicorn.error` and `uvicorn.access` loggers (`tests/test_log_redaction.py`).

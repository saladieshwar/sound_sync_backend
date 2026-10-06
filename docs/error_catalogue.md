# Error Catalogue (BE → QA, FE)

Source of truth: `app/core/errors.py`. Every error response has this shape:

```json
{ "error": { "code": "EMAIL_ALREADY_REGISTERED", "message": "An account with this email already exists", "details": {} } }
```

`message` is safe to show to users. `details` carries machine-readable context (e.g. field errors).

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
| `NOT_FOUND` | 404 | Unknown route |
| `METHOD_NOT_ALLOWED` | 405 | Wrong HTTP method for a route |
| `HTTP_ERROR` | varies | Any other framework-level HTTP error |
| `INTERNAL_ERROR` | 500 | Unhandled server error; internal details are never included |

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
| `GET /songs/category/{name}` | `200` songs in that category; unknown → `[]` | — |
| `GET /songs/albums`, `GET /songs/album/{name}` | `200` | — |
| `GET /songs/{song_id}` | `200` song | `404 SONG_NOT_FOUND`; non-integer id → `422 VALIDATION_ERROR` |
| `POST /users/me/liked-songs/{song_id}` | `201` `{ song, liked_at }`; liking again returns the same like | `404 SONG_NOT_FOUND`, `401 INVALID_TOKEN` |
| `DELETE /users/me/liked-songs/{song_id}` | `204`; also `204` if the song was not liked | `401 INVALID_TOKEN` |
| `GET /users/me/liked-songs` | `200` newest first | `401 INVALID_TOKEN` |
| `POST /users/me/recently-played/{song_id}` | `201` `{ song, played_at }` | `404 SONG_NOT_FOUND`, `401 INVALID_TOKEN` |
| `GET /users/me/recently-played?limit=` | `200` play history, most recent first (`limit` 1–100, default 20) | `422 VALIDATION_ERROR`, `401 INVALID_TOKEN` |

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

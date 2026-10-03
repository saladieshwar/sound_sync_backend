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
| `NOT_ROOM_CONTROLLER` | 403 | Transfer-access by someone who is neither admin nor controller |
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

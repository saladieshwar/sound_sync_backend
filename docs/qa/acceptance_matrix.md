# Acceptance Matrix (QA) — v1.0

Status: **Reviewed and approved by leads** (Phase 1, 2026-10-03). Maps test cases to the handbook areas (auth, search, playback, library, room sync, admin) and Section 6 acceptance criteria.

Type: `API` = pytest/HTTP, `UI` = manual or scripted browser, `MD` = multi-device manual run. Phase = handbook phase where the case becomes executable.

## Auth — "Register/login with secure password handling and JWT" (BE + DATA + FE)

| ID | Case | Expected | Type | Owner | Phase |
| --- | --- | --- | --- | --- | --- |
| AUTH-01 | Register with valid username/email/password | 201, user returned without password fields | API | BE | 2 |
| AUTH-02 | Register with an already-used email (any letter case) | 409 `EMAIL_ALREADY_REGISTERED` | API | BE/DATA | 2 |
| AUTH-03 | Register with password < 8 chars or invalid email | 422 `VALIDATION_ERROR` | API | BE | 2 |
| AUTH-04 | Login with correct credentials | 200, `access_token` + user | API | BE | 2 |
| AUTH-05 | Login with wrong password / unknown email | 401 `INVALID_CREDENTIALS` (same message for both) | API | BE | 2 |
| AUTH-06 | Call a protected route with no / invalid / expired token | 401 `INVALID_TOKEN` | API | BE | 2 |
| AUTH-07 | `password_hash` in DB is a bcrypt hash; no response or log contains a plaintext password | Verified | API | DATA/BE | 2 |
| AUTH-08 | Visit a protected page while logged out | Redirect to `/login`, return to original page after login | UI | FE | 2 |
| AUTH-09 | Register form → lands on Home already logged in | Pass | UI | FE | 2 |

## Search & catalog — "Song search, category filters, album browsing" (BE + DATA + FE)

| ID | Case | Expected | Type | Owner | Phase |
| --- | --- | --- | --- | --- | --- |
| CAT-01 | Search by partial title, artist, or album (case-insensitive) | Matching seeded songs only | API | BE/DATA | 3 |
| CAT-02 | Search with no match | 200, empty list | API | BE | 3 |
| CAT-03 | Search with empty `q` | 422 `VALIDATION_ERROR` | API | BE | 3 |
| CAT-04 | `GET /songs/category/{name}` for each seeded category | Only that category's songs | API | BE/DATA | 3 |
| CAT-05 | `GET /songs/albums` and `/songs/album/{name}` | Albums with correct song counts; album songs listed | API | BE | 3 |
| CAT-06 | `GET /songs/{id}` for unknown id | 404 `SONG_NOT_FOUND` | API | BE | 3 |
| CAT-07 | Navbar search, category row, album row on Home | Render real data; clicking navigates to results | UI | FE | 3 |

## Library — "Liked songs / recently played persist correctly per user" (FE + BE + DATA)

| ID | Case | Expected | Type | Owner | Phase |
| --- | --- | --- | --- | --- | --- |
| LIB-01 | Like a song, then list liked songs | Song appears, newest first | API | BE/DATA | 3 |
| LIB-02 | Like the same song twice | Idempotent, single entry | API | BE | 3 |
| LIB-03 | Unlike a song | 204; removed from list | API | BE | 3 |
| LIB-04 | Like an unknown song | 404 `SONG_NOT_FOUND` | API | BE | 3 |
| LIB-05 | Log plays A, B, A; list recently played | Ordered A, B, A (most recent first) | API | BE/DATA | 3–4 |
| LIB-06 | User A's likes/plays are not visible to user B | Isolated per user | API | BE | 3 |
| LIB-07 | Like toggle in song rows and footer stays in sync; persists after reload | Pass | UI | FE | 3–4 |

## Playback — "Footer player: play/pause/seek/volume/like fully functional" (FE + BE)

| ID | Case | Expected | Type | Owner | Phase |
| --- | --- | --- | --- | --- | --- |
| PLY-01 | Play a song from any list | Audio plays; footer shows title/artist/cover | UI | FE | 4 |
| PLY-02 | Play/pause, next, previous (restart if > 3 s in) | Correct behaviour | UI | FE | 4 |
| PLY-03 | Seek via slider | Playback resumes within ±0.5 s of the chosen position | UI | FE | 4 |
| PLY-04 | Volume and mute; reload page | Volume persists; mute toggles correctly | UI | FE | 4 |
| PLY-05 | Like while a song is playing | Playback uninterrupted; like state updates | UI | FE | 4 |
| PLY-06 | Each new song played creates a recently-played entry | Entry logged per user | API/UI | BE/FE | 4 |
| PLY-07 | Now Playing page shows current song and queue | Pass | UI | FE | 4 |

## Room sync — "Room creation…", "Multi-device playback stays synchronized", "Control-access transfer…", "Leave room cleans up…" (RT + BE + DATA + FE)

| ID | Case | Expected | Type | Owner | Phase |
| --- | --- | --- | --- | --- | --- |
| ROOM-01 | Create room | 201; 8-char Room ID; `join_link` = `{FRONTEND_BASE_URL}/room/{id}`; creator is admin + controller | API | BE/DATA | 5 |
| ROOM-02 | Join via Room ID and via join link | Both succeed; participant listed on all clients | API/UI | BE/FE | 5 |
| ROOM-03 | Opening a join link shows a "Join Room" prompt; no auto-join | Pass | UI | FE | 5 |
| ROOM-04 | WS connect without REST join / with bad token / to closed room | Socket closed with code 1008 | API | RT | 5 |
| ROOM-05 | Controller plays, pauses, seeks, changes song | All connected clients follow within agreed drift tolerance | MD | RT/FE | 5 |
| ROOM-06 | Non-controller sends a playback event (incl. crafted WS message) | `error` `NOT_ROOM_CONTROLLER` to sender; nothing broadcast | API | RT | 5 |
| ROOM-07 | Transfer control admin → participant → admin | `access_transfer` broadcast; only new controller can drive playback | MD | RT/BE/FE | 5 |
| ROOM-08 | Non-admin, non-controller calls transfer-access | 403 `NOT_ROOM_CONTROLLER` | API | BE | 5 |
| ROOM-09 | Participant leaves | Participant row deleted; `user_left` on all clients; control returns to admin if leaver was controller | API/MD | BE/DATA/RT | 5 |
| ROOM-10 | Admin leaves mid-session | Room `closed`; `room_closed` sent; all clients return to room landing | MD | BE/RT/FE | 5 |
| ROOM-11 | Network drop and reconnect | Client reconnects, receives `room_state`, resyncs | MD | RT/FE | 5–6 |
| ROOM-12 | Malformed WS message / unknown event type | `error` returned; socket and room session stay up | API | RT | 5 |

## Admin — "Admin can upload songs and view users/rooms" (FE + BE + DATA)

| ID | Case | Expected | Type | Owner | Phase |
| --- | --- | --- | --- | --- | --- |
| ADM-01 | Admin uploads audio + cover with metadata | 201; song searchable; files served under `/media` | API/UI | BE/FE | 5–6 |
| ADM-02 | Non-admin calls any `/admin/*` endpoint | 403 `ADMIN_REQUIRED` | API | BE | 2+ |
| ADM-03 | Non-admin opens `/admin` in the UI | Redirected to Home; no Admin nav link | UI | FE | 2+ |
| ADM-04 | Admin views users and active rooms | Lists match DB | UI | FE/BE | 5–6 |
| ADM-05 | Admin deletes a song | Removed; likes/plays cascade-deleted | API | BE/DATA | 6 |

## Resilience — "Invalid input / disconnects do not crash the app or room session" (BE + RT + QA)

| ID | Case | Expected | Type | Owner | Phase |
| --- | --- | --- | --- | --- | --- |
| RES-01 | All error responses use `{ "error": { code, message, details } }` | Pass | API | BE | 2+ |
| RES-02 | DB down | `/health` 200, `/ready` 503 | API | BE | 1 |
| RES-03 | Kill a client mid-room | Others get `user_left` (`disconnected`); room continues | MD | RT | 5 |

## Phase 1 smoke checks

| ID | Case | Expected | Owner |
| --- | --- | --- | --- |
| P1-01 | `GET /health` | 200 `{"status": "ok"}` | BE |
| P1-02 | `GET /ready` with DB up | 200 `{"database": "up"}` | BE/DATA |
| P1-03 | `/openapi.json` lists auth, songs, library, rooms, admin routes | Pass (`tests/test_health.py`) | BE |
| P1-04 | FE shell loads; `/login` shows "API online" | Pass | FE |
| P1-05 | Fresh machine can bring up DB from `backend/README.md` | Pass | DATA |

## Phase 2 results — Authentication & User Foundation

Run 2026-10-03. Backend: `pytest` (36 passed). Frontend: `npm test` (32 passed). Live API run against PostgreSQL 18 on the same day.

| ID | Result | Evidence |
| --- | --- | --- |
| AUTH-01 | Pass | `test_register_returns_user_without_password_fields`; live `POST /auth/register` → 201 |
| AUTH-02 | Pass | `test_register_duplicate_email_rejected`, `test_register_duplicate_email_is_case_insensitive`, `test_register_concurrent_duplicate_returns_409_not_500`; DB `ix_users_email` + `ck_users_email_lowercase`; live upper-case duplicate → 409 |
| AUTH-03 | Pass | `test_register_invalid_input_rejected` (bad email, short / 73-char / 74-byte password, blank username); live 100-char password → 422 |
| AUTH-04 | Pass | `test_login_returns_jwt_and_user`, `test_login_email_is_case_insensitive`; live login → bearer JWT |
| AUTH-05 | Pass | `test_login_wrong_password_and_unknown_email_look_identical` |
| AUTH-06 | Pass | `test_me_rejects_missing_or_malformed_token`, `test_me_rejects_expired_token`, `test_me_rejects_token_signed_with_another_secret`, `test_me_rejects_token_without_exp`, `test_me_rejects_token_for_unknown_user` |
| AUTH-07 | Pass | `test_password_is_stored_as_bcrypt_hash_never_plaintext`, `test_no_auth_response_contains_the_plaintext_password`; DB `ck_users_password_hash_bcrypt`; all stored hashes are `$2b$12$…` (60 chars) |
| AUTH-08 | Pass | `ProtectedRoute.test.jsx` (anonymous → `/login`, expired token → `/login`), `LoginPage.test.jsx` (returns to the originally requested page) |
| AUTH-09 | Pass | `RegisterPage.test.jsx` (register → logged in → Home, JWT in `localStorage`) |
| ADM-02 | Pass | `test_admin_route_forbidden_for_regular_user` |
| ADM-03 | Pass | `AdminRoute` tests in `ProtectedRoute.test.jsx` |
| RES-01 | Pass | `_assert_error` shape check in every negative auth test; `test_unknown_route_uses_structured_error`, `test_unhandled_exception_returns_structured_500` |

## Review sign-off

| Lead | Team | Approved | Date | Notes |
| --- | --- | --- | --- | --- |
| Eshwar (saladieshwar) | FE | Yes | 2026-10-03 | Screens/routes match AUTH, CAT, LIB, PLY, ROOM, ADM UI cases |
| Eshwar (saladieshwar) | BE | Yes | 2026-10-03 | Error codes match `docs/error_catalogue.md` |
| Eshwar (saladieshwar) | RT | Yes | 2026-10-03 | ROOM cases match `docs/websocket_contract.md` v1.0 |
| Eshwar (saladieshwar) | DATA | Yes | 2026-10-03 | Seed fixtures cover CAT/LIB cases |
| Eshwar (saladieshwar) | QA | Yes | 2026-10-03 | Matrix approved as Phase 1 baseline |

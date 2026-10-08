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

## Phase 3 results — Music Catalog & Library

Run 2026-10-03. Backend: `pytest` (98 passed; 62 new in `tests/test_songs.py` and `tests/test_library.py`). Frontend: `npm test` (64 passed; 32 new). DB at migration `0003`; `alembic check` reports no drift. Catalog tests run against exactly the seed catalog (`catalog` fixture). Live API run against PostgreSQL 18 on the same day.

| ID | Result | Evidence |
| --- | --- | --- |
| CAT-01 | Pass | `test_cat01_search_matches` (partial title, upper-case, artist, album, padded query, title ordering), `test_search_treats_wildcards_literally`; live `q=rain` → Grey Rain |
| CAT-02 | Pass | `test_cat02_search_no_match_returns_empty_list` (incl. `%`, `_`, `\`); live `q=zzz` and `q=%` → `[]` |
| CAT-03 | Pass | `test_cat03_search_invalid_query_is_422` (missing, empty, blank, > 100 chars); live blank `q` → 422 |
| CAT-04 | Pass | `test_cat04_category_filter` (all 4 seeded categories + case-insensitive), `test_unknown_category_returns_empty_list`; live `/songs/category/sad` → Grey Rain, Letters Unsent |
| CAT-05 | Pass | `test_cat05_list_albums` (4 albums × 2 songs, cover URLs), `test_cat05_album_songs`; live `/songs/albums`; cover served at `/media/covers/calm-skies.svg` |
| CAT-06 | Pass | `test_cat06_unknown_song_is_404`; live `/songs/999999` → 404 `SONG_NOT_FOUND` |
| CAT-07 | Pass | `HomePage.test.jsx` (categories/albums/all songs render API data, loading + error/retry, category and album cards navigate), `SearchPage.test.jsx` (navbar search → results, no-match, blank query ignored), `BrowsePage.test.jsx` |
| LIB-01 | Pass | `test_lib01_like_then_list_newest_first`; live like → listed → cleaned up |
| LIB-02 | Pass | `test_lib02_like_twice_is_idempotent`; concurrent duplicate like handled in `library_service.like_song` |
| LIB-03 | Pass | `test_lib03_unlike_removes_song`, `test_unlike_song_that_is_not_liked_is_noop`, `test_like_unlike_like_again` |
| LIB-04 | Pass | `test_lib04_like_unknown_song_is_404`, `test_log_play_unknown_song_is_404` |
| LIB-05 | Pass | `test_lib05_recently_played_most_recent_first` (A, B, A → A, B, A), `test_recently_played_limit`; Home shows each song once (`LibraryContext.test.jsx`, `HomePage.test.jsx`) |
| LIB-06 | Pass | `test_lib06_library_is_isolated_per_user`; all library routes reject missing/invalid JWT (`test_library_requires_valid_jwt`) |
| LIB-07 | Pass (Phase 3 scope) | `HomePage.test.jsx` (like in All Songs appears in Liked Songs; unlike removes it; buttons reflect `aria-pressed`), `LibraryContext.test.jsx` (state loaded from the server on login, so likes persist after reload). Footer player shares the same `likedIds`; re-verified with playback in Phase 4 |
| ADM-05 | Pass (DB) | `test_deleting_song_removes_it_from_libraries` (likes/plays cascade-deleted); admin UI flow remains Phase 6 |

## Phase 4 results — Home Player & Now Playing

Run 2026-10-03. Backend: `pytest` (108 passed; 10 new in `tests/test_playback.py`). Frontend: `npm test` (103 passed; 39 new in `PlayerContext.test.jsx`, `FooterPlayer.test.jsx`, `NowPlayingPage.test.jsx`). DB at migration `0004`. Scripted UI checks drive the real `PlayerProvider`/`LibraryProvider` with a fake media element (`FakeAudio` in `src/testUtils.jsx`); live checks streamed every seed WAV from the API.

| ID | Result | Evidence |
| --- | --- | --- |
| PLY-01 | Pass | `plays a song from the media server and logs the play once`, `shows song metadata and wires play events to the API`; live: all 8 seed songs served as `audio/wav`, file length = catalog `duration_seconds` |
| PLY-02 | Pass | `pauses and resumes without restarting`, queue navigation suite (next, last-song no-op, previous restarts when > 3 s, previous goes back near start, auto-advance on `ended`, stop after last), `play/pause, next and previous buttons drive the player`, `disables Next on the last song in the queue` |
| PLY-03 | Pass | `seeks to the exact requested position` (42.5 s → 42.5 s), `clamps seeks…`, `seeks accurately on release, and ignores live progress while dragging` (100.5 s, within ±0.5 s), `commits keyboard seeks on key release`; BE `test_audio_supports_range_requests_for_seeking`; live range request → 206 |
| PLY-04 | Pass | `persists volume across reloads`, `persists mute across reloads`, `sanitizes a stored volume…`, `volume and mute apply immediately and persist after reload` |
| PLY-05 | Pass | `likes and unlikes mid-playback without interrupting the song` (footer), `likes the current song without interrupting playback` (Now Playing), `volume changes do not interrupt playback` |
| PLY-06 | Pass | FE: one `logPlay` per song start, none on pause/resume or restart; BE `test_each_play_event_is_logged_for_the_right_user`, LIB-05 ordering tests; live `POST /users/me/recently-played/{id}` → 201 and listed newest first |
| PLY-07 | Pass | `NowPlayingPage.test.jsx` (metadata, play state, current song marked in Up Next, like, play from queue) |
| LIB-07 | Pass | Footer like button shares `likedIds` with song rows and Now Playing; covered above (Phase 3 + Phase 4) |
| RES-01 | Pass | `test_missing_audio_is_structured_404`; player shows "Can't play this song" for a broken file and retries on Play |

Data — recently-played performance target (p95 ≤ 10 ms, index-only plan): met; see "Recently-played performance" in `docs/schema.md` and `test_recently_played_query_uses_index_without_sort`.

Manual browser check (run once per release): log in, play a song from Home, then confirm audio is heard, seek lands where released, volume/mute survive a page reload, liking mid-song does not interrupt audio, and the song appears first in Recently Played.

## Phase 5 results — Musical Room

Run 2026-10-03. Backend: `pytest` (159 passed; 51 new — 29 in `tests/test_rooms.py`, 22 in `tests/test_room_sync.py`). Frontend: `npm test` (161 passed; 58 new in `RoomPage`, `RoomLandingPage`, `ParticipantList`, `LeaveRoomButton`, `useRoomSocket`, `events`, `rooms` utils, and room-sync cases in `PlayerContext`). DB at migration `0004` (room tables from `0001`; no new migration needed). `MD` cases are evidenced by real multi-client WebSocket runs: `tests/test_room_sync.py` (live uvicorn server, 2–3 `websockets` clients) and `python -m scripts.room_sync_check` against a running API.

Drift tolerance agreed for ROOM-05: **0.5 s** (`websocket_contract.md` v1.1). Live harness, 3 clients × 80 events: delivery latency **p50 9.8 ms, p95 14.5 ms, max 26 ms**.

Update 2026-10-07 (contract v1.2): clients now estimate the server clock with `time_sync` and correct drift without ever changing the playback rate (one small settle jump after play / seek / join with a learned per-device resume delay, then no corrections unless the gap exceeds 150 ms), so devices with skewed clocks or slow buffering land within ~40 ms without choppy audio, instead of staying up to 0.5 s (or a full clock skew) apart. Backend 161 passed (2 new `time_sync` tests); frontend 172 passed (new `serverClock`, `time_sync` hook, timeline and drift-correction tests).

| ID | Result | Evidence |
| --- | --- | --- |
| ROOM-01 | Pass | `test_create_room_makes_creator_admin_controller_and_participant` (8-char upper-case ID, trimmed name), `test_create_room_returns_shareable_join_link`, `test_room_ids_are_unique`, `test_create_room_rejects_invalid_name`; FE `creates a room with a trimmed name and opens it` |
| ROOM-02 | Pass | Room ID: `test_join_by_room_id_adds_participant`, `test_join_is_idempotent`; link (lower-case ID): `test_join_is_case_insensitive_like_a_typed_room_id`, WS `test_join_link_lowercase_room_id_connects`; FE `joins by a typed Room ID in any letter case`, `joins by a pasted join link`, `updates participants as people join and leave`; harness "joined by Room ID" / "joined via join link" |
| ROOM-03 | Pass | FE `opening a join link shows a Join Room prompt and does not auto-join` (no REST join and no socket until **Join Room** is clicked) |
| ROOM-04 | Pass | `test_socket_rejected_without_rest_join`, `test_socket_rejected_with_bad_token`, `test_socket_rejected_for_closed_room` (all close `1008`; socket accepted first so browsers read the code); FE `does not retry when the server closes with 1008` |
| ROOM-05 | Pass | `test_play_pause_seek_song_change_sync_across_three_clients` (every client gets the persisted state; each delivery < 0.5 s), `test_room_state_reflects_persisted_playback`; harness p95 14.5 ms; FE `cannot drive playback and follows play, seek and pause broadcasts`, `joins a playing room at the current position` (±0.5 s), `leaves small gaps to the settle step and jumps on large ones`, `follows the room timeline on the server clock, not the device clock`, `lands in sync with one small jump on a device that resumes late, then leaves audio alone`, `never jumps for small measurement jitter`, `resyncs once audio falls clearly behind mid-song`, `uses the learned resume delay so later resyncs need one jump only`; BE `test_time_sync_is_answered_only_to_the_sender` |
| ROOM-06 | Pass | `test_non_controller_events_are_rejected_and_not_broadcast` (crafted `play` and `song_change` → `NOT_ROOM_CONTROLLER`, other clients receive nothing), `test_playback_event_requires_controller`; FE listener controls disabled |
| ROOM-07 | Pass | `test_transfer_control_both_directions` (WS: `access_transfer` on all clients; only the new controller can drive playback, old controller rejected), REST `test_transfer_access_both_directions`, `test_admin_can_take_back_control_from_controller`, `test_new_controller_can_drive_playback_after_transfer`; FE `gives control to a participant`, `takes over the controls when control is transferred to them`; harness admin → bob → admin |
| ROOM-08 | Pass | `test_only_admin_or_controller_can_transfer` (403 `NOT_ROOM_CONTROLLER`), `test_transfer_to_non_participant_is_403` |
| ROOM-09 | Pass | `test_leave_removes_participant_row`, `test_controller_leaving_returns_control_to_admin`, `test_leave_when_not_participant_is_403`; WS `test_participant_leave_closes_their_socket_and_notifies_room` (`user_left` `reason: left` with new controller; leaver's socket closed `1000`); FE `leaving calls the API, stops room audio and returns to the landing page` |
| ROOM-10 | Pass | `test_admin_leaving_closes_room_and_clears_participants`, WS `test_admin_leave_mid_session_closes_room_for_everyone` (3 clients get `room_closed`, sockets close `1000`, room → 410); FE `returns everyone to the landing page when the admin closes the room`; harness "Admin leaves mid-session" |
| ROOM-11 | Pass | WS `test_network_drop_then_reconnect_resyncs` (drop → `user_left` `disconnected`; reconnect → `room_state` with the position/pause state set while offline; next broadcast received); FE `reconnects after a network drop and resyncs from room_state`, `useRoomSocket` `reconnects after a network drop`; harness "Network drop and reconnect" |
| ROOM-12 | Pass | `test_bad_messages_get_error_and_socket_stays_up` (non-JSON, missing/unknown type, server-only type, bad position, `song_change` without song, `NO_CURRENT_SONG`, `SONG_NOT_FOUND` — socket keeps working after each), `test_binary_frame_gets_error_and_socket_stays_up`; FE ignores malformed frames, shows friendly error text |
| RES-03 | Pass | `test_network_drop_then_reconnect_resyncs` (other clients get `user_left` `disconnected`; room keeps playing), `test_second_tab_does_not_duplicate_presence` |

Manual two-device check (run once per release; setup in `backend/README.md` → "Multi-device room testing"): on device A create a room and copy the join link; on device B open the link and tap **Join Room** (also try typing the Room ID). Pick a song on A and confirm B hears it in step; pause, seek, and change song on A and confirm B follows within about half a second. Give control to B, drive playback from B, then give it back. Turn B's Wi-Fi off for ~10 s and on again: B shows **Reconnecting…**, then **Live**, and jumps to the room position. Leave on B (red **Leave Room** button) — B returns to the landing page and disappears from A's list. Finally leave on A — B is sent to the landing page with "The room was closed by its admin."

## Phase 6 results — Integration & Performance

Run 2026-10-07. Backend: `pytest` (202 passed; new `tests/test_e2e.py`, `tests/test_performance.py`, `tests/test_network_sync.py`, `tests/test_admin.py`, `tests/test_log_redaction.py`; shared live-server helpers in `tests/live.py`). Frontend: `npm test` (186 passed; new `journey.test.jsx`, `AdminPage.test.jsx`, auth retry and asymmetric-jitter clock tests), `npm run lint` (warnings only, no errors), `npm run build` OK. DB at migration `0005` (`search_text` + one trigram index, room FK and active-room indexes, `clock_timestamp()` room `created_at`); `alembic check` reports no drift; downgrade/upgrade verified. Sync targets and tuning notes: `docs/sync_tuning.md`.

Scripts run against a live API + Vite build in headless Edge (two isolated browser profiles = two devices): `python -m scripts.browser_e2e` (all steps Pass; listener vs controller audio median 5–46 ms, max ≤ 69 ms, ≤ 1 correction jump), `python -m scripts.perf_smoke` (all budgets Pass), `python -m scripts.sync_benchmark` (all network profiles Pass), `python -m scripts.benchmark_catalog_rooms` (all budgets Pass).

New cases:

| ID | Case | Expected | Type | Owner |
| --- | --- | --- | --- | --- |
| E2E-01 | One API session across all modules: health → auth → catalog → library → room create/join → WS sync → transfer → leave → room closed | Every step returns the documented status/payload; WS events < 0.5 s | API/MD | BE/QA |
| E2E-02 | One UI session: register → home → search → player → room → leave | No reload, no logout, URL path sequence as expected | UI | FE/QA |
| E2E-03 | Two real browsers: login, home, play, room create/join, sync, transfer, leave, admin upload/delete | All steps Pass; listener audio within 150 ms of controller, ≤ 1 jump | UI/MD | QA |
| PERF-01 | Catalog search on 50,000 songs | p95 ≤ 25 ms (3+ chars), ≤ 100 ms (1–2 chars); trigram index used | DB | DATA |
| PERF-02 | Room join with 2,000 rooms / 20,000 participants | p95 ≤ 50 ms; lookups use indexes | DB | DATA |
| PERF-03 | 10 concurrent users on the API (reads, writes, joins, broadcast, auth) | Within the budgets in `docs/sync_tuning.md` | API | QA |
| SYNC-01 | Sync under LAN / Wi-Fi / 4G / poor network | Agreement p95 ≤ 40 ms (≤ 150 ms poor); reaction p95 ≤ 250 ms (≤ 500 ms poor) | MD | RT |
| SEC-01 | Server logs while clients connect with `?token=<JWT>` | No JWT in any log line (`token=[redacted]`) | API | BE |
| RES-04 | API briefly unreachable while a logged-in user reloads | Stays logged in, shows "Reconnecting…", resumes when the API is back | UI | FE |

| ID | Result | Evidence |
| --- | --- | --- |
| E2E-01 | Pass | `test_full_journey_register_browse_play_room_sync_leave` (live uvicorn server, real HTTP + 2 WebSocket clients) |
| E2E-02 | Pass | `journey.test.jsx` `completes register -> home -> player -> room -> leave in one uninterrupted session` (real `App`, all providers and routes) |
| E2E-03 | Pass | `scripts/browser_e2e.py` run (see above) |
| PERF-01 | Pass | `test_search_of_three_plus_chars_uses_the_trigram_index`, `test_search_matches_any_field_case_insensitively_but_not_across_fields`; benchmark 4–8 ms (3+ chars), 51 ms (1–2 chars) |
| PERF-02 | Pass | `test_room_lookups_use_indexes`, `test_room_join_flow_meets_budget`; benchmark p95 15 ms, lookups 0.04–0.12 ms |
| PERF-03 | Pass | `scripts/perf_smoke.py`: reads 11–21 ms, log play 25–39 ms, 9 simultaneous joins 162–181 ms, broadcast 14 ms, auth 0.6–1.1 s |
| SYNC-01 | Pass | `test_sync_meets_targets_under_network_profile` (all 4 profiles), `test_server_clock_mirror_uses_min_rtt_sample`, `test_proxy_adds_delay_and_preserves_order`; FE `serverClock` asymmetric-jitter cases; agreement p95 lan 1.1, wifi 4.2, 4g 10.4, poor 29.9 ms |
| SEC-01 | Pass | `test_server_logs_never_contain_the_jwt`, `test_install_is_idempotent_and_runs_with_the_app`, `test_redact_leaves_other_text_alone`; live server log checked: 0 JWTs |
| RES-04 | Pass | `AuthContext.test.jsx` `keeps the stored token and retries while the server is unreachable` |
| ADM-01 | Pass | `test_upload_creates_searchable_song_with_served_files`, `test_upload_without_cover_or_album`, `test_upload_rejects_unsupported_file_types` (415), `test_upload_rejects_oversized_files_and_cleans_up` (413), `test_upload_rejects_empty_audio`, `test_upload_validates_metadata`; FE `uploads the form as multipart data and confirms`, `shows the API reason when an upload is rejected`, `only offers supported file types in the picker`; browser admin flow (upload → searchable → audio served) |
| ADM-02 | Pass | `test_admin_routes_require_admin` (every `/admin/*` route) |
| ADM-04 | Pass | `test_admin_lists_users_without_secrets`, `test_admin_lists_only_active_rooms_newest_first`; FE `lists users with their role`, `lists active rooms`, `shows an error with retry instead of an empty table when loading fails`, `says so when there are no active rooms`; browser admin flow (Users and Rooms tabs) |
| ADM-05 | Pass | `test_admin_delete_removes_song_library_rows_and_files`, `test_admin_delete_keeps_files_other_songs_still_use`, `test_admin_delete_unknown_song_is_404`; FE `deletes a song after confirmation and refreshes the list`, `does nothing when the confirmation is cancelled`; browser admin flow (delete → 404) |
| ROOM-05 | Pass | Re-verified under realistic networks (SYNC-01) and in real browsers (E2E-03) |
| ROOM-11 | Pass | Re-verified: `test_network_drop_then_reconnect_resyncs` in the full run |

Regression: every Phase 1–5 case above was re-run in the same `pytest` / `npm test` run (all green).

## Phase 7 results — Documentation & Packaging

Run 2026-10-07. Backend: `pytest` (220 passed; 18 new: `tests/test_docs.py`, `tests/test_check_db.py`, error-path tests in `test_auth.py`, `test_health.py`, `test_room_sync.py`). Frontend: `npm test` (186 passed), lint and build OK. Documentation pack and checklist: `docs/documentation_checklist.md`, which includes the clean-copy verification run.

| ID | Case | Expected | Result | Evidence |
| --- | --- | --- | --- | --- |
| DOC-01 | Clean machine builds and runs from the docs | Fresh venv + `npm ci` from tracked source only; tests, build and API start succeed | Pass | `documentation_checklist.md` → "Verification run" (220 + 186 tests, `/health` `/ready` `/docs` 200) |
| DOC-02 | Every setting documented | Every `Settings` field in `.env.example` and `setup_guide.md` | Pass | `test_every_setting_is_in_env_example_and_setup_guide` |
| DOC-03 | OpenAPI is final | Snapshot equals the running code | Pass | `test_openapi_snapshot_matches_the_code` |
| DOC-04 | WebSocket reference complete | Every event and error code documented; ordering guarantees enforced | Pass | `test_websocket_contract_lists_every_event_and_error_code`, `test_joiner_mid_burst_sees_events_in_commit_order_with_no_gap` (5/5 repeated runs) |
| DOC-05 | QA can recreate fixtures from docs | `check_db` all OK after runbook steps (fresh server: setup, migrate, seed; and reset path); expected seed results match the API | Pass | `test_check_db_passes_on_a_migrated_seeded_database`, `test_check_db_detects_missing_or_changed_seed_rows`; clean-copy seed + `check_db`; runbook expectations checked against the live API |
| DOC-06 | Backup is restorable | Full restore onto a fresh server reproduces every table, row, index, constraint, sequence, extension, migration version and media file; app works on the copy | Pass | `python -m scripts.restore_check` (21 × OK, empty restore and `--clean` restore); `pytest` 220 passed on the restored copy; `db_runbook.md` section 8 |
| DOC-07 | UI guide complete | Every route and API function documented | Pass | `test_every_frontend_route_is_in_the_ui_guide`, `test_every_frontend_api_function_is_in_the_ui_guide` |
| DOC-08 | Error suite documented and passing | Every REST and WebSocket error code documented, tested and handled in the UI | Pass | `docs/qa/error_crosscheck.md`; `test_error_crosscheck_covers_every_code_with_existing_passing_tests` |
| DOC-09 | Documentation pack consistent | All relative links resolve; every documented script exists | Pass | `test_relative_links_resolve`, `test_documented_scripts_exist` |
| RES-02 | DB down | `/health` 200, `/ready` 503 | Pass (now automated) | `test_ready_is_503_when_database_is_down` |
| ROOM-05 | Multi-device sync | Late joiner never misses an event | Pass (hardened) | Per-room ordering lock; `test_joiner_mid_burst_sees_events_in_commit_order_with_no_gap` |

Defects found and fixed during Phase 7:

- A device joining while the controller was seeking could miss that event and stay on an old position until the next action. Fixed by per-room serialization (contract v1.3).
- After a WebSocket `ROOM_CLOSED` error the socket ended without a close frame, so the client retried pointlessly. The server now closes with `1008`.
- `FORBIDDEN` and `USER_NOT_FOUND` were defined but never used, so they were removed.
- `/songs/categories` was missing from the error catalogue.
- The backend repo tracked `venv/`, `.venv/` and `__pycache__` (16,000+ files); they are now untracked.

## Phase 8 results — Hardening, UAT and Handover (release 1.0.0)

Run 2026-10-07. Backend: `pytest` (240 passed; new `tests/test_data_integrity.py`, the playing-song delete test in `tests/test_room_sync.py`, QA-record and release-package checks in `tests/test_docs.py`). Frontend: `npm test` (189 passed), `npm run lint` (0 errors, 4 known warnings), `npm run build` OK. WebSocket contract v1.4. Section 6 sign-off: [`uat_evidence_pack.md`](uat_evidence_pack.md).

| ID | Case | Expected | Result | Evidence |
| --- | --- | --- | --- | --- |
| BENCH-01 | Sync latency and drift on LAN, Wi-Fi, 4G, poor network and in real browsers | All targets in `sync_tuning.md` met; report accepted by QA | Pass | [`benchmark_report.md`](benchmark_report.md) |
| DEF-01 | Defect burn-down | No Sev-1 or Sev-2 open on core paths; every fix has evidence | Pass | [`defect_log.md`](defect_log.md) (20 closed, 0 open); `test_docs::test_defect_log_has_nothing_open_and_every_fix_has_evidence` |
| ADM-06 | Admin deletes the song a room is playing | Every device in the room stops; new joiners see no song; play needs a new song | Pass | `test_room_sync::test_admin_deleting_the_playing_song_stops_the_room_for_everyone`; FE `RoomPage.test.jsx` |
| UX-01 | Every screen at phone, tablet and desktop size | No sideways scroll or cut-off content, player never hides content, named controls, 24 px targets, no script errors | Pass | `python -m scripts.ux_check` 30 / 30; [`ux_review.md`](ux_review.md) |
| UX-02 | Login and register forms with a screen reader and password manager | Fields named, autofill hints, errors announced | Pass | FE `LoginPage.test.jsx`, `RegisterPage.test.jsx` |
| DATA-01 | Delete rules and indexes on the final schema | Database, models and checklist agree; every foreign key indexed; deletes remove exactly the right rows | Pass | `test_data_integrity::test_delete_rules_match_in_database_models_and_checklist`, `test_data_integrity::test_every_foreign_key_is_indexed_so_deletes_never_scan`; [`data_checklist.md`](data_checklist.md) |
| DATA-02 | Backup of the final schema restores | Restore check all OK; tests pass on the copy | Pass | `python -m scripts.restore_check`; [`data_checklist.md`](data_checklist.md) |
| UAT-01 | All handbook Section 6 criteria | 11 of 11 Pass with evidence; stakeholder accepts | Pass | [`uat_evidence_pack.md`](uat_evidence_pack.md); `test_docs::test_uat_pack_passes_every_section_6_criterion_with_evidence` |
| KT-01 | Team can build, run and extend from the package and docs alone | Clean copy builds, runs, and accepts a new endpoint with tests | Pass | [`../handover.md`](../handover.md) "Handover verification" (241 tests after the extension) |
| REL-01 | Source package | Only source; no virtualenv, cache, media or `.env`; checksums | Pass | `python -m scripts.package_release`; `test_docs::test_release_package_refuses_secrets_environments_and_build_output` |
| E2E-03 | Two real browsers, full journey | All steps Pass | Pass (3 runs in a row, 30 / 30) | `python -m scripts.browser_e2e` |

Regression: every Phase 1–7 case above was re-run in the same `pytest` / `npm test` run (all green).

## Review sign-off

| Lead | Team | Approved | Date | Notes |
| --- | --- | --- | --- | --- |
| Eshwar (saladieshwar) | FE | Yes | 2026-10-03 | Screens/routes match AUTH, CAT, LIB, PLY, ROOM, ADM UI cases |
| Eshwar (saladieshwar) | BE | Yes | 2026-10-03 | Error codes match `docs/error_catalogue.md` |
| Eshwar (saladieshwar) | RT | Yes | 2026-10-03 | ROOM cases match `docs/websocket_contract.md` v1.1 |
| Eshwar (saladieshwar) | DATA | Yes | 2026-10-03 | Seed fixtures cover CAT/LIB cases |
| Eshwar (saladieshwar) | QA | Yes | 2026-10-03 | Matrix approved as Phase 1 baseline |
| Eshwar (saladieshwar) | QA | Yes | 2026-10-07 | Phase 6: critical E2E green, no broken sync on normal networks, all performance budgets met |
| Eshwar (saladieshwar) | ALL | Yes | 2026-10-07 | Phase 7: documentation checklist satisfied; error suite documented and passing |
| Eshwar (saladieshwar) | QA | Yes | 2026-10-07 | Phase 8: benchmark report accepted, no open defects, UX and DATA checklists signed, all Section 6 criteria accepted |
| Eshwar (saladieshwar) | ALL | Yes | 2026-10-07 | Phase 8: handover complete; release 1.0.0 delivered |

# Error-Handling Cross-Check (QA)

Every error the system can return, checked three ways: is it **documented**, is it **tested**, and does the **frontend** handle it. Run 2026-10-07 against the code at contract v1.3: every row passes.

How this page stays true: `tests/test_docs.py` fails if a code exists in the code but not in the docs (or the other way round), if a test named below no longer exists, or if a WebSocket code has no frontend message.

Run the error suite:

```powershell
cd backend
pytest tests/test_docs.py tests/test_auth.py tests/test_health.py tests/test_songs.py tests/test_library.py tests/test_rooms.py tests/test_room_sync.py tests/test_admin.py tests/test_playback.py tests/test_log_redaction.py
cd ../frontend
npx vitest run src/api src/context src/pages src/realtime
```

## REST errors

Shape `{ "error": { code, message, details } }`; documented in [`../error_catalogue.md`](../error_catalogue.md).

| Code | HTTP | Tests (backend `tests/`) | Frontend handling | Result |
| --- | --- | --- | --- | --- |
| `VALIDATION_ERROR` | 422 | `test_auth::test_register_invalid_input_rejected`, `test_auth::test_login_overlong_password_is_validation_error`, `test_songs::test_cat03_search_invalid_query_is_422`, `test_songs::test_list_songs_rejects_bad_pagination`, `test_library::test_recently_played_rejects_bad_limit`, `test_rooms::test_create_room_rejects_invalid_name`, `test_admin::test_upload_validates_metadata` | `getApiError` names the first bad field; forms show it (`client.test.js`, `RegisterPage.test.jsx`) | Pass |
| `EMAIL_ALREADY_REGISTERED` | 409 | `test_auth::test_register_duplicate_email_rejected`, `test_auth::test_register_duplicate_email_is_case_insensitive`, `test_auth::test_register_concurrent_duplicate_returns_409_not_500` | Shown on the register form | Pass |
| `INVALID_CREDENTIALS` | 401 | `test_auth::test_login_wrong_password_and_unknown_email_look_identical` | Shown on the login form (`LoginPage.test.jsx`) | Pass |
| `INVALID_TOKEN` | 401 | `test_auth::test_me_rejects_missing_or_malformed_token`, `test_auth::test_me_rejects_expired_token`, `test_auth::test_me_rejects_token_signed_with_another_secret`, `test_auth::test_me_rejects_token_without_exp`, `test_auth::test_me_rejects_token_for_unknown_user`, `test_health::test_protected_route_requires_token`, `test_library::test_library_requires_valid_jwt` | Any 401 clears the token and logs out (`AuthContext.test.jsx` "logs out when any API call reports the session is unauthorized") | Pass |
| `ADMIN_REQUIRED` | 403 | `test_admin::test_admin_routes_require_admin`, `test_auth::test_admin_route_forbidden_for_regular_user` | `/admin` hidden and redirected for non-admins (`ProtectedRoute.test.jsx`) | Pass |
| `SONG_NOT_FOUND` | 404 | `test_songs::test_cat06_unknown_song_is_404`, `test_library::test_lib04_like_unknown_song_is_404`, `test_library::test_log_play_unknown_song_is_404`, `test_admin::test_admin_delete_unknown_song_is_404`, `test_rooms::test_song_change_to_unknown_song_is_rejected` | Message shown; in a room: "That song is no longer available." | Pass |
| `ROOM_NOT_FOUND` | 404 | `test_rooms::test_join_unknown_room_is_404` | Message shown on the room landing page | Pass |
| `ROOM_CLOSED` | 410 | `test_rooms::test_join_closed_room_is_410`, `test_room_sync::test_admin_leave_mid_session_closes_room_for_everyone` | Message shown; open room view returns to `/room` | Pass |
| `NOT_ROOM_PARTICIPANT` | 403 | `test_rooms::test_get_room_is_for_participants_only`, `test_rooms::test_leave_when_not_participant_is_403`, `test_rooms::test_transfer_to_non_participant_is_403` | Opening a room you have not joined shows the **Join Room** prompt (`RoomPage.test.jsx`) | Pass |
| `NOT_ROOM_CONTROLLER` | 403 | `test_rooms::test_only_admin_or_controller_can_transfer`, `test_rooms::test_playback_event_requires_controller` | Message shown | Pass |
| `NO_CURRENT_SONG` | 409 | `test_rooms::test_play_without_song_is_rejected` | "Pick a song for the room first." | Pass |
| `UNSUPPORTED_FILE_TYPE` | 415 | `test_admin::test_upload_rejects_unsupported_file_types` | Admin form shows the reason; file picker only offers allowed types (`AdminPage.test.jsx`) | Pass |
| `FILE_TOO_LARGE` | 413 | `test_admin::test_upload_rejects_oversized_files_and_cleans_up` | Admin form shows the reason | Pass |
| `NOT_FOUND` | 404 | `test_auth::test_unknown_route_uses_structured_error`, `test_playback::test_missing_audio_is_structured_404` | Missing audio: "Can't play this song" with retry (`FooterPlayer.test.jsx`) | Pass |
| `METHOD_NOT_ALLOWED` | 405 | `test_auth::test_wrong_method_uses_structured_error` | Not reachable from the UI | Pass |
| `HTTP_ERROR` | other | `test_auth::test_other_framework_http_errors_use_structured_error` | Generic message | Pass |
| `INTERNAL_ERROR` | 500 | `test_auth::test_unhandled_exception_returns_structured_500` (internal detail never leaked) | Generic message; auth check retries instead of logging out (`AuthContext.test.jsx`) | Pass |

## WebSocket errors

Sent as `{ "type": "error", "payload": { "code" } }`; documented in [`../websocket_contract.md`](../websocket_contract.md) → "Error codes". The socket stays open, except after `ROOM_CLOSED`. Friendly texts: `ROOM_ERROR_MESSAGES` in `frontend/src/realtime/events.js`.

| Code | Tests (backend `tests/`) | Frontend message | Result |
| --- | --- | --- | --- |
| `INVALID_MESSAGE` | `test_room_sync::test_bad_messages_get_error_and_socket_stays_up` (not JSON, no type, unknown type), `test_room_sync::test_binary_frame_gets_error_and_socket_stays_up` | "Something went wrong sending that action. Please try again." | Pass |
| `INVALID_PAYLOAD` | `test_room_sync::test_bad_messages_get_error_and_socket_stays_up` (negative position, `song_change` without song), `test_room_sync::test_time_sync_without_client_ts_is_invalid` | same | Pass |
| `EVENT_NOT_ALLOWED` | `test_room_sync::test_bad_messages_get_error_and_socket_stays_up` (client sends `room_closed`) | "That action is not allowed in a room." | Pass |
| `NOT_ROOM_CONTROLLER` | `test_room_sync::test_non_controller_events_are_rejected_and_not_broadcast`, `test_room_sync::test_transfer_control_both_directions`, `test_e2e::test_full_journey_register_browse_play_room_sync_leave` | "Only the current controller can change playback." | Pass |
| `NO_CURRENT_SONG` | `test_room_sync::test_bad_messages_get_error_and_socket_stays_up` (`play` before a song) | "Pick a song for the room first." | Pass |
| `SONG_NOT_FOUND` | `test_room_sync::test_bad_messages_get_error_and_socket_stays_up` (`song_change` to song 0) | "That song is no longer available." | Pass |
| `ROOM_CLOSED` | `test_room_sync::test_playback_after_room_closed_meanwhile_gets_room_closed_then_1008` (error, then close `1008`) | "This room has been closed."; the page re-checks via REST | Pass |

## Close codes and other failure paths

| Case | Tests | Result |
| --- | --- | --- |
| Socket without REST join / bad token / closed room → `1008` | `test_room_sync::test_socket_rejected_without_rest_join`, `test_room_sync::test_socket_rejected_with_bad_token`, `test_room_sync::test_socket_rejected_for_closed_room`; FE `useRoomSocket.test.jsx` (no retry on `1008`) | Pass |
| Leave / room closed → `1000` | `test_room_sync::test_participant_leave_closes_their_socket_and_notifies_room`, `test_room_sync::test_admin_leave_mid_session_closes_room_for_everyone` | Pass |
| Network drop → reconnect and resync | `test_room_sync::test_network_drop_then_reconnect_resyncs`; FE `useRoomSocket.test.jsx`, `RoomPage.test.jsx` | Pass |
| Database down → `/ready` 503, `/health` 200 | `test_health::test_ready_is_503_when_database_is_down` | Pass |
| API unreachable from the browser | FE `AuthContext.test.jsx` "keeps the stored token and retries while the server is unreachable"; `getApiError` → `NETWORK_ERROR` | Pass |
| Rejected upload leaves no files behind | `test_admin::test_upload_rejects_oversized_files_and_cleans_up` | Pass |
| No JWT in server logs | `test_log_redaction::test_server_logs_never_contain_the_jwt` | Pass |

## Findings fixed during this cross-check

| Finding | Fix |
| --- | --- |
| `FORBIDDEN` and `USER_NOT_FOUND` were defined in `errors.py` but never returned or documented | Removed |
| `METHOD_NOT_ALLOWED`, `HTTP_ERROR`, WebSocket `ROOM_CLOSED` and `/ready` 503 had no test | Tests added (named above) |
| After a WebSocket `ROOM_CLOSED` error the server ended the socket without a close frame, so browsers saw an abnormal close and retried | Server now closes with `1008` (contract v1.3) |
| `GET /songs/categories` was missing from the catalogue's examples | Added |

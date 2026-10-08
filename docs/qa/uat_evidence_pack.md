# UAT Evidence Pack and Acceptance Sign-off (QA, Phase 8)

Handbook Phase 8: "QA: Full acceptance + UAT sign-off. Deliverable: evidence pack against Section 6 criteria. Done when: stakeholder accepts delivery."

Release **SoundSync 1.0.0**: API 1.0.0, frontend 1.0.0, database migration `0005`, WebSocket contract v1.4. Every case ID below is defined in [`acceptance_matrix.md`](acceptance_matrix.md). `tests/test_docs.py` checks that every test named on this page exists and that all 11 criteria are present and passed.

## Final run (2026-10-07)

| Suite | Command (from the repo root) | Result |
| --- | --- | --- |
| Backend tests (live server, WebSockets, network profiles, docs) | `pytest` | 240 passed |
| Frontend tests | `npm test` | 189 passed (23 files) |
| Frontend lint and build | `npm run lint`, `npm run build` | 0 errors (4 known warnings); build OK |
| Two real browsers, full journey | `python -m scripts.browser_e2e` | 30 / 30 steps, three runs in a row |
| Screens at phone, tablet, desktop | `python -m scripts.ux_check` | 30 / 30 |
| Room engine | `python -m scripts.room_sync_check` | 13 / 13 |
| Sync under four network profiles | `python -m scripts.sync_benchmark` | All Pass ([`benchmark_report.md`](benchmark_report.md)) |
| Load and database budgets | `python -m scripts.perf_smoke`, `python -m scripts.benchmark_catalog_rooms` | All Pass, 0 errors |
| Backup restored onto a fresh server | `python -m scripts.restore_check` | 20 × OK; full `pytest` passed on the copy ([`data_checklist.md`](data_checklist.md)) |
| Release package | `python -m scripts.package_release` | PASS: no virtualenv, cache, media or `.env` |

Open defects: **0** (20 found and closed, [`defect_log.md`](defect_log.md)).

## Section 6 acceptance criteria

| # | Criterion (handbook Section 6) | Cases | Automated evidence | Real-browser / UAT evidence | Result |
| --- | --- | --- | --- | --- | --- |
| C-01 | Register/login works with secure password handling and JWT | AUTH-01 to AUTH-09, SEC-01 | `test_auth::test_password_is_stored_as_bcrypt_hash_never_plaintext`, `test_auth::test_login_wrong_password_and_unknown_email_look_identical`, `test_auth::test_me_rejects_expired_token`, `test_log_redaction::test_server_logs_never_contain_the_jwt`; FE `LoginPage.test.jsx`, `RegisterPage.test.jsx`, `ProtectedRoute.test.jsx` | `browser_e2e` "anonymous visitor is sent to /login", "both users registered and landed on Home" | Pass |
| C-02 | Song search, category filters, and album browsing function correctly | CAT-01 to CAT-07, PERF-01 | `test_songs::test_cat01_search_matches`, `test_songs::test_cat04_category_filter`, `test_songs::test_cat05_album_songs`, `test_performance::test_search_of_three_plus_chars_uses_the_trigram_index`; FE `HomePage.test.jsx`, `SearchPage.test.jsx`, `BrowsePage.test.jsx` | `browser_e2e` "navbar search shows results"; search p95 ≤ 8 ms on 50,000 songs | Pass |
| C-03 | Liked songs and recently played persist correctly per user | LIB-01 to LIB-07, PLY-06 | `test_library::test_lib01_like_then_list_newest_first`, `test_library::test_lib05_recently_played_most_recent_first`, `test_library::test_lib06_library_is_isolated_per_user`, `test_playback::test_each_play_event_is_logged_for_the_right_user`; FE `LibraryContext.test.jsx` | `browser_e2e` "play is logged to Recently Played", "like is saved" (checked through the API) | Pass |
| C-04 | Footer player supports play/pause/seek/volume/like and is fully functional | PLY-01 to PLY-07 | `test_playback::test_audio_supports_range_requests_for_seeking`, `test_playback::test_missing_audio_is_structured_404`; FE `PlayerContext.test.jsx`, `FooterPlayer.test.jsx`, `NowPlayingPage.test.jsx` | `browser_e2e` "plays through the real <audio>"; `ux_check` footer at every size ([`ux_review.md`](ux_review.md)) | Pass |
| C-05 | Room creation generates a valid shareable link and Room ID | ROOM-01 to ROOM-03 | `test_rooms::test_create_room_returns_shareable_join_link`, `test_rooms::test_room_ids_are_unique`, `test_rooms::test_join_is_case_insensitive_like_a_typed_room_id`, `test_room_sync::test_join_link_lowercase_room_id_connects`; FE `RoomLandingPage.test.jsx`, `RoomPage.test.jsx` | `browser_e2e` "join link ends with the Room ID", "second device joined via the join link"; `room_sync_check` joins by ID and by link | Pass |
| C-06 | Multi-device playback stays synchronized | ROOM-05, ROOM-11, SYNC-01, E2E-03 | `test_room_sync::test_play_pause_seek_song_change_sync_across_three_clients`, `test_room_sync::test_joiner_mid_burst_sees_events_in_commit_order_with_no_gap`, `test_room_sync::test_admin_deleting_the_playing_song_stops_the_room_for_everyone`, `test_network_sync::test_sync_meets_targets_under_network_profile`; FE `serverClock.test.js`, `PlayerContext.test.jsx` | Two browsers within 47 ms, 0 correction jumps; two listeners ≤ 8.2 ms apart (p95) on 4G ([`benchmark_report.md`](benchmark_report.md)) | Pass |
| C-07 | Control-access transfer works in both directions and is enforced server-side | ROOM-06 to ROOM-08 | `test_room_sync::test_transfer_control_both_directions`, `test_room_sync::test_non_controller_events_are_rejected_and_not_broadcast`, `test_rooms::test_only_admin_or_controller_can_transfer`, `test_rooms::test_admin_can_take_back_control_from_controller`; FE `RoomPage.test.jsx`, `ParticipantList.test.jsx` | `browser_e2e` "bob now controls playback", "new controller's song plays on the admin's device"; `room_sync_check` admin → bob → admin | Pass |
| C-08 | Leave room cleans up participant state across all clients | ROOM-09, ROOM-10 | `test_rooms::test_leave_removes_participant_row`, `test_rooms::test_controller_leaving_returns_control_to_admin`, `test_room_sync::test_participant_leave_closes_their_socket_and_notifies_room`, `test_room_sync::test_admin_leave_mid_session_closes_room_for_everyone`, `test_data_integrity::test_deleting_a_room_removes_only_its_participants`; FE `LeaveRoomButton.test.jsx` | `browser_e2e` "participant leaves; control returns to the admin", "admin leaving closes the room" | Pass |
| C-09 | Admin can upload songs and view users/rooms | ADM-01 to ADM-05 | `test_admin::test_upload_creates_searchable_song_with_served_files`, `test_admin::test_admin_routes_require_admin`, `test_admin::test_admin_lists_users_without_secrets`, `test_admin::test_admin_lists_only_active_rooms_newest_first`, `test_admin::test_admin_delete_removes_song_library_rows_and_files`; FE `AdminPage.test.jsx` | `browser_e2e` admin steps (upload, searchable, served, users, rooms, delete); `ux_check` admin tabs at every size | Pass |
| C-10 | Invalid input and network disconnects do not crash the app or room session | RES-01 to RES-04, ROOM-04, ROOM-11, ROOM-12 | `test_room_sync::test_bad_messages_get_error_and_socket_stays_up`, `test_room_sync::test_binary_frame_gets_error_and_socket_stays_up`, `test_room_sync::test_network_drop_then_reconnect_resyncs`, `test_health::test_ready_is_503_when_database_is_down`, `test_auth::test_unhandled_exception_returns_structured_500`; FE `useRoomSocket.test.jsx`, `AuthContext.test.jsx`; every error code in [`error_crosscheck.md`](error_crosscheck.md) | `room_sync_check` "drop reported", "reconnect resyncs position"; `ux_check` no script errors on any screen | Pass |
| C-11 | Documentation, test harness, and benchmark results are delivered | DOC-01 to DOC-09 | `test_docs::test_relative_links_resolve`, `test_docs::test_openapi_snapshot_matches_the_code`, `test_docs::test_documented_scripts_exist`, `test_docs::test_qa_docs_name_only_existing_tests` | [`../documentation_checklist.md`](../documentation_checklist.md), [`../handover.md`](../handover.md), [`benchmark_report.md`](benchmark_report.md), rerunnable `scripts/` | Pass |

## How a stakeholder reruns UAT (about 15 minutes)

1. Start PostgreSQL, the API and the frontend as in [`../setup_guide.md`](../setup_guide.md), then `python -m scripts.seed`.
2. In `backend/`: `pytest`, then `python -m scripts.browser_e2e` and `python -m scripts.ux_check`. Each prints PASS per step.
3. By hand on two devices (laptop and phone on the same Wi-Fi), follow the "Manual two-device check" in [`acceptance_matrix.md`](acceptance_matrix.md) (Phase 5 section): create a room, join by link, play, pause, seek, transfer control both ways, drop Wi-Fi, leave.
4. Log in as `admin@soundsync.dev` (password in [`../db_runbook.md`](../db_runbook.md)), upload a song, check the Users and Rooms tabs, delete the song.

## Stakeholder acceptance

| Role | Name | Decision | Date | Notes |
| --- | --- | --- | --- | --- |
| QA lead | Eshwar (saladieshwar) | Accepted | 2026-10-07 | All 11 Section 6 criteria pass with evidence; 0 open defects |
| Product owner / stakeholder | Eshwar (saladieshwar) | Accepted | 2026-10-07 | Delivery accepted as SoundSync 1.0.0 |

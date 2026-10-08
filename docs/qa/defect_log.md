# Defect Log and Burn-down (QA, Phase 8)

Handbook Phase 8: "BE: Defect burn-down on API/orchestration. Deliverable: critical/high defects closed. Done when: no Sev-1 open on core paths." and "FE: UI/UX defect burn-down. Deliverable: player, room, and admin UX clearly functional. Done when: UX signed off for UAT." Bugs carry a severity and an owning team, as the QA contract requires.

`tests/test_docs.py` checks this page: no row may be open, and every row must name evidence that exists (a test, a script or a screenshot).

## Severity

| Severity | Meaning | Example |
| --- | --- | --- |
| Sev-1 | Critical: a core path is broken, data is lost, or security is breached; no workaround | Users cannot log in; a secret leaks |
| Sev-2 | High: a core feature works wrongly or unreliably; a workaround exists | Devices in a room drift apart |
| Sev-3 | Medium: a secondary problem, accessibility or layout issue; the feature still works | A button too small to tap comfortably |
| Sev-4 | Low: cosmetic or housekeeping | An unused error code |

Core paths (handbook Section 6): register/login, search and browse, liked songs and recently played, footer player, room create/join, multi-device sync, control transfer, leave room, admin upload and lists, resilience to bad input and disconnects.

## Status

| | Sev-1 | Sev-2 | Sev-3 | Sev-4 | Total |
| --- | --- | --- | --- | --- | --- |
| Found | 1 | 7 | 8 | 4 | 20 |
| Closed | 1 | 7 | 8 | 4 | 20 |
| **Open** | **0** | **0** | **0** | **0** | **0** |

**No Sev-1 or Sev-2 defect is open on any core path.** Every fix has a regression test or a rerunnable check.

## Defects

| ID | Severity | Team | Area | Found | Defect | Fix | Evidence | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| D-01 | Sev-1 | BE | Security | Phase 6 | The server access log wrote the full JWT of every WebSocket connection (`?token=` in the URL), against the rule "no raw JWT secrets in logs" | A log filter replaces it with `token=[redacted]` in every logger, installed with the app | `test_log_redaction::test_server_logs_never_contain_the_jwt` | Closed |
| D-02 | Sev-2 | BE | Auth | Phase 2 | Two registrations with the same email at the same moment could fail with `500` instead of `409` | The unique-violation from the database is turned into `409 EMAIL_ALREADY_REGISTERED` | `test_auth::test_register_concurrent_duplicate_returns_409_not_500` | Closed |
| D-03 | Sev-2 | RT | Room sync | Phase 5 | A socket refused during the handshake showed up in browsers as close code `1006`, so the client kept retrying instead of stopping | The server accepts first, then closes with `1008` (contract v1.1) | `test_room_sync::test_socket_rejected_for_closed_room`, FE `useRoomSocket.test.jsx` | Closed |
| D-04 | Sev-2 | RT | Room sync | Phase 5 | Devices with wrong clocks or slow audio start played up to 0.5 s (or a whole clock error) apart | Server-clock estimate over `time_sync`, playback follows the room timeline, small settle jumps instead of rate changes (contract v1.2) | `test_room_sync::test_time_sync_is_answered_only_to_the_sender`, `test_network_sync::test_sync_meets_targets_under_network_profile`, FE `serverClock.test.js` | Closed |
| D-05 | Sev-2 | DATA | Search | Phase 6 | On a large catalog, search sometimes skipped its indexes and scanned every song (250–500 ms on 50,000 songs) | Migration `0005`: one pre-lowered `search_text` column with one trigram index | `test_performance::test_search_of_three_plus_chars_uses_the_trigram_index` | Closed |
| D-06 | Sev-2 | FE | Auth | Phase 6 | Reloading the app while the API was briefly unreachable logged the user out | The token is kept and the session check retries until the API answers | FE `AuthContext.test.jsx` | Closed |
| D-07 | Sev-2 | RT | Room sync | Phase 7 | A device joining while the controller was seeking could miss that event and stay on an old position until the next action | Per-room lock: connect, playback and REST broadcasts are serialized (contract v1.3) | `test_room_sync::test_joiner_mid_burst_sees_events_in_commit_order_with_no_gap` | Closed |
| D-08 | Sev-2 | BE | Admin / room sync | Phase 8 | When an admin deleted the song a room was playing, devices already in the room kept playing it (its file was gone) while new joiners heard nothing, so the room was out of sync | The delete also stops those rooms and the server broadcasts a `pause` with no song under the room lock (contract v1.4) | `test_room_sync::test_admin_deleting_the_playing_song_stops_the_room_for_everyone`, FE `RoomPage.test.jsx` | Closed |
| D-09 | Sev-3 | RT | Room sync | Phase 5 | A user with two tabs open was announced twice (`user_joined` / `user_left` per tab) | Presence is tracked per user, not per socket | `test_room_sync::test_second_tab_does_not_duplicate_presence` | Closed |
| D-10 | Sev-3 | DATA | Rooms | Phase 6 | Deleting a user scanned every room because the room foreign keys had no index | Migration `0005` indexes all three room foreign keys | `test_performance::test_room_lookups_use_indexes`, `test_data_integrity::test_every_foreign_key_is_indexed_so_deletes_never_scan` | Closed |
| D-11 | Sev-3 | RT | Room sync | Phase 7 | After an `error` `ROOM_CLOSED` the socket ended without a close frame, so clients retried pointlessly | The server closes with `1008` | `test_room_sync::test_playback_after_room_closed_meanwhile_gets_room_closed_then_1008` | Closed |
| D-12 | Sev-3 | FE | Accessibility | Phase 8 | Login and register fields had only a placeholder (screen readers announced "edit text"), no autofill hints, and errors were not announced | Fields have names and `autocomplete`; errors use `role="alert"` | FE `LoginPage.test.jsx`, FE `RegisterPage.test.jsx`, `python -m scripts.ux_check` | Closed |
| D-13 | Sev-3 | FE | Player / navbar | Phase 8 | The Logout button (20 px tall) and every slider (16 px: seek, volume, room seek) were below the 24 px minimum touch target | Larger hit areas | `python -m scripts.ux_check` | Closed |
| D-14 | Sev-3 | QA | Test suite | Phase 8 | Two frontend tests failed now and then on a busy machine: one read the last socket message, which could be a clock probe; one expected an exact millisecond; waits gave up after 1 s | Ignore clock probes, compare positions to 0.1 s, 3 s wait limit for the whole suite | FE `journey.test.jsx`, FE `PlayerContext.test.jsx` (3 full runs in a row, 187 of 187) | Closed |
| D-20 | Sev-3 | QA | Test harness | Phase 8 | The browser end-to-end run failed at "join via the join link" whenever `FRONTEND_BASE_URL` was a LAN address (set for phone testing): the second browser opened another origin where it was not logged in | The harness checks the link ends with `/room/{Room ID}` and opens that path on the app address it was given | `python -m scripts.browser_e2e` (3 runs in a row, 30 of 30 steps) | Closed |
| D-15 | Sev-3 | BE | Packaging | Phase 7 | The backend repository tracked `venv/`, `.venv/` and `__pycache__` (16,000+ files) | Untracked and git-ignored; the release package is checked for them | `python -m scripts.package_release` | Closed |
| D-16 | Sev-4 | FE | Admin | Phase 8 | The upload form's file pickers were unstyled, so "Choose File" did not look like a button | Styled as buttons | `docs/qa/ux/admin-upload-phone.jpg` | Closed |
| D-17 | Sev-4 | FE | Player | Phase 8 | On tablets the footer player cut the song title to a few letters because the volume column took a third of the width | The volume column takes only the space it needs | `docs/qa/ux/now-playing-tablet.jpg` | Closed |
| D-18 | Sev-4 | BE | Errors | Phase 7 | `FORBIDDEN` and `USER_NOT_FOUND` were defined but never returned | Removed | `test_docs::test_error_catalogue_lists_exactly_the_rest_error_codes` | Closed |
| D-19 | Sev-4 | BE | Release | Phase 8 | The API reported version `0.1.0` and the frontend `0.0.0` | Both are `1.0.0` | `test_docs::test_openapi_snapshot_matches_the_code` | Closed |

## Known limitations (accepted, not defects)

| Limitation | Why it is accepted | Where documented |
| --- | --- | --- |
| The API must run as one process: the room hub is in memory | The handbook architecture ("in-memory connection manager"); one process handled every budget in `sync_tuning.md` | [`setup_guide.md`](../setup_guide.md) section 6 |
| Wide admin tables scroll sideways on phones | Admin work is mainly done on a laptop; the page itself never scrolls sideways | [`ux_review.md`](ux_review.md) |
| `npm run lint` shows 4 warnings (React fast-refresh and compiler hints) | Hints only; no errors, and behaviour is covered by tests | [`../../../frontend/README.md`](../../../frontend/README.md) |
| A phone browser may block audio until the user taps once | Browser autoplay policy; the room shows **Tap to hear the room** | [`ui_guide.md`](../../../frontend/docs/ui_guide.md) |

## Sign-off

| Lead | Team | Signed | Date | Notes |
| --- | --- | --- | --- | --- |
| Eshwar (saladieshwar) | BE | Yes | 2026-10-07 | All critical/high defects closed; no Sev-1 open on core paths |
| Eshwar (saladieshwar) | FE | Yes | 2026-10-07 | All UI/UX defects closed; see `ux_review.md` |
| Eshwar (saladieshwar) | QA | Yes | 2026-10-07 | Every fix retested; regression suite green |

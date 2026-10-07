# WebSocket Event Contract (RT → FE/BE)

Status: **Frozen v1.2** (Phase 5). Source of truth: `app/realtime/events.py`. Changes require notifying BE and FE before merge.

## Changelog

| Version | Date | Change |
| --- | --- | --- |
| v1.0 | 2026-10-03 | Phase 1 baseline |
| v1.1 | 2026-10-03 | Phase 5 delivery. Additive only: playback broadcasts carry the authoritative `is_playing`; `room_state` adds `online_user_ids`; new `error` codes `NO_CURRENT_SONG`, `SONG_NOT_FOUND`, `ROOM_CLOSED`; close codes documented; presence events are per user (second tab does not re-announce); rejected sockets are accepted then closed with `1008` so browsers can read the code |
| v1.2 | 2026-10-07 | Additive only: `time_sync` event (client clock-offset estimation, answered to the sender only); clients follow the room timeline on the server clock with continuous drift correction instead of a 0.5 s seek-only tolerance. Phase 6: no message changes; measured sync under realistic networks and the agreed tolerance are in `docs/sync_tuning.md` |

## Connection

1. Client joins via REST: `POST /rooms/{room_id}/join` (Bearer JWT). Room IDs are case-insensitive.
2. Client connects: `ws://<host>/rooms/{room_id}/ws?token=<JWT>`. (Browsers cannot set headers on a WebSocket, hence the query string; the server redacts `token=` from its logs, see `docs/error_catalogue.md` → "Logging".)
3. Server closes with code `1008` if the token is invalid, the room is closed or unknown, or the user has not joined via REST.
4. On accept, the server sends `room_state` to the new socket and, if this is the user's first socket in the room, broadcasts `user_joined` to everyone else.

### Close codes

| Code | Sent when | Client should |
| --- | --- | --- |
| `1000` | User left via REST (`reason: "left"`), or the room was closed (after `room_closed`) | Leave the room view; do **not** reconnect |
| `1008` | Not allowed: bad token, not a participant, room closed/unknown | Do **not** reconnect; re-check via REST (`GET /rooms/{id}`) |
| other (`1006`, `1001`, `1011`…) | Network drop, server restart | Reconnect (FE retries every 2 s); the new `room_state` resyncs playback |

## Message shapes

Client → server:

```json
{ "type": "seek", "payload": { "position_seconds": 42.5 } }
{ "type": "song_change", "payload": { "position_seconds": 0, "song_id": 3 } }
```

Server → client (playback broadcast, sent to **every** socket in the room including the sender):

```json
{ "type": "seek", "payload": { "song_id": 3, "position_seconds": 42.5, "is_playing": true }, "sender_user_id": 7, "server_ts": 1780000000000 }
```

The broadcast payload is the room state **as persisted** (position clamped to the song length), not an echo of the client payload. `server_ts` is epoch milliseconds on the **server** clock.

### Clock sync (`time_sync`)

Device clocks can differ from the server by a second or more, so clients never compare `server_ts` with their own `Date.now()`. Instead they estimate the server clock NTP-style:

```json
{ "type": "time_sync", "payload": { "client_ts": 1780000000000 } }
{ "type": "time_sync", "payload": { "client_ts": 1780000000000 }, "sender_user_id": 7, "server_ts": 1780000001512 }
```

The server answers only the sender, echoing `client_ts` and stamping `server_ts`. With `received` = local time the reply arrived:
`rtt = received - client_ts`, `offset = server_ts - (client_ts + rtt / 2)`, `server_now = Date.now() + offset`.
The FE sends 5 samples 200 ms apart on every connect, then one every 30 s, and uses the sample with the lowest `rtt` (`frontend/src/realtime/serverClock.js`). `time_sync` is never broadcast and never changes room state.

### Room timeline

Each playback event defines a timeline: the room is at `position_seconds` at server time `server_ts`. While `is_playing`:
`expected_position = position_seconds + (server_now - server_ts) / 1000`.

For `room_state`, first advance the snapshot to `server_ts`: `position_seconds + (server_ts - state_updated_at) / 1000` while `is_playing`.

**Drift correction** (constants in `frontend/src/realtime/events.js`). Clients never change `playbackRate`: browsers time-stretch audio at any rate other than 1.0, which sounds choppy on phones. Every 250 ms a client reads its drift from `expected_position`; decisions use the median of 4 readings, so one noisy reading never triggers a jump.

| When | Action |
| --- | --- |
| After a play / seek / join (settling) | Once audio has run 0.75 s, if the gap is > 40 ms, make one small jump; up to 3 tries, usually 1 |
| Settled, gap ≤ 150 ms | Leave the audio alone (no jumps for the rest of the song) |
| Settled, gap > 150 ms (e.g. after a network stall) | Jump back in sync, then settle again |

Each jump lands at `expected_position + seek_lead`, where `seek_lead` is learned per device from how late its audio resumes after the client's own jumps, so after the first jump on a device later jumps land on time.

Buffering is skipped (no correction while the audio is stalled) and caught up afterwards. Measured delivery latency on a LAN host is ~10 ms p50 / ~15 ms p95 (`scripts/room_sync_check.py`).

## Event types

| Type | Direction | Payload |
| --- | --- | --- |
| `play` | client → server | `position_seconds` |
| `pause` | client → server | `position_seconds` |
| `seek` | client → server | `position_seconds` |
| `song_change` | client → server | `position_seconds`, `song_id` (required) |
| `play` / `pause` / `seek` / `song_change` | server → client | `song_id`, `position_seconds`, `is_playing` |
| `access_transfer` | server → client | `controller_user_id` |
| `user_joined` | server → others | `user_id` (user's first socket only) |
| `user_left` | server → client | `user_id`, `reason` (`left` / `disconnected`), `controller_user_id` (when `left`) |
| `room_state` | server → new socket | full `RoomOut` snapshot + `online_user_ids` |
| `room_closed` | server → client | `{}` (admin left; sockets then close with `1000`) |
| `time_sync` | client → server → sender | `client_ts` (epoch ms, echoed back with `server_ts`) |
| `error` | server → sender | `code` (see below); the socket stays open unless noted |

Client `song_id` on `play`/`pause`/`seek` is optional and ignored; the server uses the room's current song.

### Error codes

| Code | When |
| --- | --- |
| `INVALID_MESSAGE` | Not JSON, binary frame, missing `type`, or unknown event type |
| `INVALID_PAYLOAD` | `position_seconds` missing / negative / > 86400, `song_change` without `song_id`, or `time_sync` without a numeric `client_ts` |
| `EVENT_NOT_ALLOWED` | Client sent a server-only event (`room_state`, `access_transfer`, …) |
| `NOT_ROOM_CONTROLLER` | Sender is not the current `controller_user_id` |
| `NO_CURRENT_SONG` | `play` / `pause` / `seek` before any `song_change` |
| `SONG_NOT_FOUND` | `song_change` to an unknown song |
| `ROOM_CLOSED` | Room was closed meanwhile; the socket is then closed |

Rejected messages are never broadcast and never change room state.

## Rules

- Only playback events (`play`, `pause`, `seek`, `song_change`) and `time_sync` are accepted from clients. `time_sync` needs no controller rights.
- A playback event is applied and broadcast only if the sender is the room's current `controller_user_id`, read from the DB under a row lock on each message (never trusted from the client), so a transfer that commits first always wins.
- Accepted playback events are persisted through BE (`room_service.apply_playback_event`) before broadcast. `song_change` starts playing; `pause` stops; `seek` keeps the current play state.
- Control transfer happens over REST (`POST /rooms/{id}/transfer-access`); RT then broadcasts `access_transfer`.
- Socket disconnect does not remove room membership; only REST leave does. REST leave closes that user's sockets (`1000`) and broadcasts `user_left` with `reason: "left"`.
- Presence is per user: a user with two tabs is online until their last socket closes.

## Room data BE exposes to RT

Shape: `RoomOut` in `app/schemas/room.py`, backed by `musical_rooms` + `room_participants`.

| Field | Type | Notes |
| --- | --- | --- |
| `id` | string (8 chars, upper-case) | Room ID used in REST paths, the WS path, and the join link |
| `name` | string | 1–100 chars, trimmed |
| `admin_user_id` | int | Room creator; leaving closes the room |
| `controller_user_id` | int / null | Only this user's playback events are applied |
| `current_song_id` | int / null | |
| `is_playing` | bool | |
| `position_seconds` | float | Playback position at `state_updated_at` |
| `state_updated_at` | datetime (UTC) | Used with `server_ts` for drift reconciliation |
| `status` | `active` / `closed` | WS connections are refused when `closed` |
| `participants[]` | `{ user: { id, username }, joined_at }` | A row exists only after REST join |
| `join_link` | string | `{FRONTEND_BASE_URL}/room/{id}` |
| `online_user_ids` | int[] | `room_state` only: users with at least one open socket |

BE → RT interface:

- RT authorizes sockets via `room_service.get_active_room_or_404` + `room_repo.get_participant`.
- RT writes playback state only through `room_service.apply_playback_event`; it never writes tables directly. `room_service.playback_payload` builds the broadcast payload.
- BE calls RT through `app/realtime/sync_facade.py` (`connect`, `disconnect`, `broadcast`, `validate_controller`, `remove_user`, `close_room`) after REST transfer-access and leave.

## Sign-off

| Team | Acknowledged by | Date |
| --- | --- | --- |
| RT | Eshwar (saladieshwar) | 2026-10-03 |
| BE | Eshwar (saladieshwar) | 2026-10-03 |
| FE | Eshwar (saladieshwar) | 2026-10-03 |

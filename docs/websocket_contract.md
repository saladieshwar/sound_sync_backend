# WebSocket Event Contract (RT → FE/BE)

Status: **Frozen v1.3** (Phase 7). Source of truth: `app/realtime/events.py`. Changes require notifying BE and FE before merge. A new engineer can build a room client from this page alone: start with "Implementing a client" at the end.

## Changelog

| Version | Date | Change |
| --- | --- | --- |
| v1.0 | 2026-10-03 | Phase 1 baseline |
| v1.1 | 2026-10-03 | Phase 5 delivery. Additive only: playback broadcasts carry the authoritative `is_playing`; `room_state` adds `online_user_ids`; new `error` codes `NO_CURRENT_SONG`, `SONG_NOT_FOUND`, `ROOM_CLOSED`; close codes documented; presence events are per user (second tab does not re-announce); rejected sockets are accepted then closed with `1008` so browsers can read the code |
| v1.2 | 2026-10-07 | Additive only: `time_sync` event (client clock-offset estimation, answered to the sender only); clients follow the room timeline on the server clock with continuous drift correction instead of a 0.5 s seek-only tolerance. Phase 6: no message changes; measured sync under realistic networks and the agreed tolerance are in `docs/sync_tuning.md` |
| v1.3 | 2026-10-07 | No message changes. Ordering guarantees documented and enforced (per-room serialization: a socket joining mid-burst can no longer miss an event committed between its `room_state` read and its registration); after an `error` `ROOM_CLOSED` the server now closes the socket with `1008` (was an unclean close that made clients retry); "Implementing a client" walkthrough |

## Connection

1. Client joins via REST: `POST /rooms/{room_id}/join` (Bearer JWT). Room IDs are case-insensitive.
2. Client connects: `ws://<host>/rooms/{room_id}/ws?token=<JWT>`. (Browsers cannot set headers on a WebSocket, hence the query string; the server redacts `token=` from its logs, see `docs/error_catalogue.md` → "Logging".)
3. Server closes with code `1008` if the token is invalid, the room is closed or unknown, or the user has not joined via REST.
4. On accept, the server sends `room_state` to the new socket and, if this is the user's first socket in the room, broadcasts `user_joined` to everyone else.

### Close codes

| Code | Sent when | Client should |
| --- | --- | --- |
| `1000` | User left via REST (`reason: "left"`), or the room was closed (after `room_closed`) | Leave the room view; do **not** reconnect |
| `1008` | Not allowed: bad token, not a participant, room closed/unknown — at connect, or after an `error` `ROOM_CLOSED` on an open socket | Do **not** reconnect; re-check via REST (`GET /rooms/{id}`) |
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
| `ROOM_CLOSED` | Room was closed meanwhile; the socket is then closed with `1008` |

Rejected messages are never broadcast and never change room state.

## Rules

- Only playback events (`play`, `pause`, `seek`, `song_change`) and `time_sync` are accepted from clients. `time_sync` needs no controller rights.
- A playback event is applied and broadcast only if the sender is the room's current `controller_user_id`, read from the DB under a row lock on each message (never trusted from the client), so a transfer that commits first always wins.
- Accepted playback events are persisted through BE (`room_service.apply_playback_event`) before broadcast. `song_change` starts playing; `pause` stops; `seek` keeps the current play state.
- Control transfer happens over REST (`POST /rooms/{id}/transfer-access`); RT then broadcasts `access_transfer`.
- Socket disconnect does not remove room membership; only REST leave does. REST leave closes that user's sockets (`1000`) and broadcasts `user_left` with `reason: "left"`.
- Presence is per user: a user with two tabs is online until their last socket closes.

## Ordering guarantees

What a client can rely on (enforced in `app/realtime/ws_routes.py` with a per-room lock, `ConnectionManager.room_lock`; tested in `tests/test_room_sync.py`):

1. **One socket is first-in, first-out.** Messages arrive in the order the server sent them.
2. **`room_state` comes first.** It is the first message on every new socket and already includes every playback event committed before it. Every later playback event arrives after it. None is missed and none is repeated, even if the controller is seeking while you connect (`test_joiner_mid_burst_sees_events_in_commit_order_with_no_gap`).
3. **One order for everyone.** A room's playback events are saved and broadcast one at a time, in commit order, so every socket in the room (including the sender's own) sees the same sequence. The sender's echo is the confirmation that its event was applied.
4. **Each message is the full truth.** Every playback broadcast carries `song_id`, `position_seconds`, `is_playing` and `server_ts`. Replace your state with the latest message; never merge or add up deltas.
5. **A client's own messages are handled in order.** The server reads the next message from a socket only after the previous one is saved and broadcast, or rejected with an `error`.
6. **Events from REST calls come after the HTTP response.** `access_transfer`, `user_left` (`reason: "left"`) and `room_closed` are sent after the REST call that caused them has answered. Update your own view from the REST response too. An `access_transfer` or `user_left` committed just before you connected can also arrive after your `room_state`; it repeats a value you already have, so applying it again is harmless.
7. **Leave and close order.** On leave, the leaver's sockets are closed (`1000`) first, then the others get `user_left`. On close, everyone gets `room_closed`, then all sockets close (`1000`).
8. **Presence.** `user_joined` is broadcast after the newcomer's `room_state`. `user_left` (`reason: "disconnected"`) is sent only when a user's last socket closes.
9. **No replay after a reconnect.** Events sent while you were offline are not re-sent. The fresh `room_state` is the complete current state.
10. **Sender-only messages can come at any point.** `time_sync` replies and `error` messages go to one socket and may arrive between broadcasts.
11. Rooms are independent; there is no ordering between different rooms.

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

## Implementing a client

Steps for any client (web, mobile, script). The reference implementations are `frontend/src/realtime/useRoomSocket.js` (connection, reconnect, `time_sync`), `frontend/src/realtime/serverClock.js` (clock), `frontend/src/realtime/events.js` (timeline and drift rules) and `frontend/src/pages/room/RoomPage.jsx` (event handling). The minimal Python client used by the tests is `backend/tests/live.py`.

1. **Log in** with `POST /auth/login` and keep `access_token`.
2. **Join over REST**: `POST /rooms` (create; you become admin and controller) or `POST /rooms/{id}/join`. `404` means there is no such room and `410` means it is closed. A WebSocket without a REST join is closed with `1008`.
3. **Connect** to `ws://<api-host>/rooms/{id}/ws?token=<access_token>` (`wss://` behind HTTPS).
4. **Sync the clock.** On open, send 5 `time_sync` messages 200 ms apart, then one every 30 s. Keep the offset from the reply with the lowest round trip (formula under "Clock sync"). Send `time_sync` again after every reconnect.
5. **On `room_state`**, store the whole room: participants, `controller_user_id`, `online_user_ids` and the timeline (see "Room timeline"). Fetch the song with `GET /songs/{current_song_id}`, play its `audio_url` (served from the API host) from `expected_position`, and pause if `is_playing` is false.
6. **On `play` / `pause` / `seek` / `song_change`**, replace the timeline with the message (guarantee 4). If `song_id` changed, load the new song. Then seek and play or pause to `expected_position`, following the drift-correction table.
7. **If you are the controller** (`controller_user_id` equals your user id), send `{ "type": "seek", "payload": { "position_seconds": 42.5 } }` and similar. `song_change` also needs `song_id`. Treat your own echo as the confirmation. Everyone else must not send playback events: they get `NOT_ROOM_CONTROLLER`.
8. **Presence and control:**
   - `user_joined` / `user_left`: update the online list.
   - `user_left` with `reason: "left"`: also remove the participant and take the new `controller_user_id`.
   - `access_transfer`: update `controller_user_id`.
   - To hand over control, call `POST /rooms/{id}/transfer-access`.
9. **On `error`**, show the message for its `code`. The socket stays open, except after `ROOM_CLOSED`.
10. **On close:**
    - `1000` after `room_closed`, or after you left: leave the room screen.
    - `1008`: call `GET /rooms/{id}` to learn why, and do not reconnect.
    - Any other code: reconnect after about 2 s and resync from the new `room_state`.
11. **Leave** with `POST /rooms/{id}/leave`. The server closes your sockets (`1000`). If you are the admin, this closes the room for everyone.

Minimal browser client (no drift correction):

```js
const ws = new WebSocket(`ws://localhost:8000/rooms/${roomId}/ws?token=${token}`)
let offset = 0, bestRtt = Infinity, timeline = null
const serverNow = () => Date.now() + offset

ws.onopen = () => {
  for (let i = 0; i < 5; i++)
    setTimeout(() => ws.send(JSON.stringify({ type: 'time_sync', payload: { client_ts: Date.now() } })), i * 200)
}
ws.onmessage = ({ data }) => {
  const msg = JSON.parse(data)
  if (msg.type === 'time_sync') {
    const rtt = Date.now() - msg.payload.client_ts
    if (rtt < bestRtt) { bestRtt = rtt; offset = msg.server_ts - (msg.payload.client_ts + rtt / 2) }
  } else if (msg.type === 'room_state') {
    const p = msg.payload
    const ahead = p.is_playing ? (msg.server_ts - Date.parse(p.state_updated_at)) / 1000 : 0
    timeline = { songId: p.current_song_id, at: p.position_seconds + ahead, ts: msg.server_ts, playing: p.is_playing }
  } else if (['play', 'pause', 'seek', 'song_change'].includes(msg.type)) {
    const p = msg.payload
    timeline = { songId: p.song_id, at: p.position_seconds, ts: msg.server_ts, playing: p.is_playing }
  }
  // expected position now: timeline.at + (timeline.playing ? (serverNow() - timeline.ts) / 1000 : 0)
}
ws.onclose = ({ code }) => {
  if (code !== 1000 && code !== 1008) { /* after 2 s, open a new socket with the same setup */ }
}
```

## Sign-off

| Team | Acknowledged by | Date |
| --- | --- | --- |
| RT | Eshwar (saladieshwar) | 2026-10-03 |
| BE | Eshwar (saladieshwar) | 2026-10-03 |
| FE | Eshwar (saladieshwar) | 2026-10-03 |
| RT / BE / FE (v1.3) | Eshwar (saladieshwar) | 2026-10-07 |

# WebSocket Event Contract (RT → FE/BE)

Source of truth: `app/realtime/events.py`. Changes require notifying BE and FE before merge.

## Connection

1. Client joins via REST: `POST /rooms/{room_id}/join` (Bearer JWT).
2. Client connects: `ws://<host>/rooms/{room_id}/ws?token=<JWT>`.
3. Server rejects with close code `1008` if the token is invalid, the room is closed, or the user has not joined via REST.
4. On accept, the server sends `room_state` to the new socket and broadcasts `user_joined` to the room.

## Message shapes

Client → server:

```json
{ "type": "play", "payload": { "position_seconds": 42.5, "song_id": 3 } }
```

Server → client:

```json
{ "type": "play", "payload": { "position_seconds": 42.5, "song_id": 3 }, "sender_user_id": 7, "server_ts": 1780000000000 }
```

`server_ts` is epoch milliseconds. Clients reconcile drift with:
`expected_position = position_seconds + (now - server_ts) / 1000` while playing.

## Event types

| Type | Direction | Payload |
| --- | --- | --- |
| `play` | client ↔ server | `position_seconds`, `song_id?` |
| `pause` | client ↔ server | `position_seconds`, `song_id?` |
| `seek` | client ↔ server | `position_seconds`, `song_id?` |
| `song_change` | client ↔ server | `position_seconds`, `song_id` |
| `access_transfer` | server → client | `controller_user_id` |
| `user_joined` | server → client | `user_id` |
| `user_left` | server → client | `user_id`, `reason` (`left` / `disconnected`), `controller_user_id?` |
| `room_state` | server → client | full `RoomOut` snapshot |
| `room_closed` | server → client | `{}` (admin left; socket is then closed) |
| `error` | server → sender | `code`: `INVALID_MESSAGE`, `INVALID_PAYLOAD`, `EVENT_NOT_ALLOWED`, `NOT_ROOM_CONTROLLER` |

`room_state`, `room_closed`, and `error` are additions to the handbook's base list of seven events.

## Rules

- Only playback events (`play`, `pause`, `seek`, `song_change`) are accepted from clients.
- A playback event is broadcast only if the sender is the room's current `controller_user_id`, read from the DB on each message (never trusted from the client).
- Accepted playback events are persisted through BE (`room_service.update_playback_state`) before broadcast.
- Control transfer happens over REST (`POST /rooms/{id}/transfer-access`); RT then broadcasts `access_transfer`.
- Socket disconnect does not remove room membership; only REST leave does.

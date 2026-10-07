# Sync Tuning Notes (RT, Phase 6)

How far apart two devices in a Musical Room may play, how that is measured under realistic networks, and the values the player uses. Contract: `docs/websocket_contract.md` v1.2. Player: `frontend/src/context/PlayerContext.jsx`, constants in `frontend/src/realtime/events.js`.

## Agreed targets

| Target | Value | Why |
| --- | --- | --- |
| **Sync tolerance** (two listeners' audio, p95) on normal networks (LAN, Wi-Fi, 4G) | **≤ 40 ms** | Below ~40 ms two speakers in one room sound like one; above it you start to hear an echo |
| Sync tolerance on a poor network (p95) | ≤ 150 ms | Must stay under the player's resync threshold (`RESYNC_SECONDS`), so the player never flaps between corrections |
| Reaction time (controller presses play/pause/seek → listener receives it, p95), normal networks | **≤ 250 ms** | Feels immediate; listeners still land on the right position because they follow the room timeline, not the arrival time |
| Reaction time, poor network (p95) | ≤ 500 ms | The acceptance drift tolerance (`DRIFT_TOLERANCE_SECONDS`, ROOM-05) |
| Real browsers on one network, listener vs controller audio (max over 25 samples) | ≤ 150 ms, and ≤ 1 correction jump once settled | No audible jumps ("song breaking") while settled |

## How sync works (short)

1. Every playback event and `room_state` carries `server_ts`. A listener plays `position + (serverNow − server_ts)`, so network delay does not move the position.
2. `serverNow` comes from an NTP-style clock estimate (`realtime/serverClock.js`): 5 `time_sync` round trips on connect (then one every 30 s), keeping the sample with the **lowest round-trip time**. Its error is at most half the up/down delay difference of that one sample, so jitter mostly cancels out. Device clocks that are seconds off do not matter.
3. The player never changes `playbackRate` (time-stretching sounds choppy on phones). After play / seek / join it waits `SETTLE_MS`, measures drift (median of `DRIFT_SAMPLES` readings), and makes up to `SETTLE_ATTEMPTS` small jumps if it is more than `IN_SYNC_SECONDS` off, learning the device's resume delay ("seek lead"). Once settled it only jumps again if drift exceeds `RESYNC_SECONDS`.

## Method

`scripts/netem_proxy.py` is a TCP proxy that adds per-direction delay, jitter and loss spikes (a portable stand-in for Linux `tc netem`; on Windows it raises the timer resolution to 1 ms so small delays are accurate). Order is preserved per direction, like TCP, so a slow chunk delays the ones behind it.

| Profile | One-way delay | Jitter (each way) | Loss spikes | Round trip |
| --- | --- | --- | --- | --- |
| `lan` | 1 ms | ±0.5 ms | — | ~2 ms |
| `wifi` | 10 ms | ±5 ms | 0.5% × +60 ms | ~20 ± 10 ms |
| `4g` | 30 ms | ±15 ms | 1% × +120 ms | ~60 ± 30 ms |
| `poor` | 75 ms | ±40 ms | 3% × +250 ms | ~150 ± 80 ms |

`scripts/sync_benchmark.py` puts three users in one room with every WebSocket going through the proxy, then measures:

- **Reaction time** — controller sends `song_change` / `seek` / `pause` / `play`; time until each listener receives it.
- **Clock error** — each listener runs the same min-RTT estimate as the browser (Python mirror `ServerClock`), starting from a device clock that is deliberately wrong by up to ±3 s. Error = estimated offset − true offset.
- **Sync agreement** — the difference between the two listeners' clock errors. Because every device positions audio from the same room timeline, this is exactly how far apart their audio plays.

The real-browser check (`scripts/browser_e2e.py`) runs two isolated headless Edge profiles against the real frontend and API and reads both `<audio>` elements' `currentTime` 25 times, 300 ms apart, after the settle step (3 s).

## Results (2026-10-07, Windows 11, local API + PostgreSQL 18)

`python -m scripts.sync_benchmark` (10 rounds × 4 events × 2 listeners, 10 clock trials per profile):

| Profile | Reaction p50 / p95 / max | Clock error p95 | Sync agreement p50 / p95 / max | Result |
| --- | --- | --- | --- | --- |
| `lan` | 13.9 / 17.8 / 19.3 ms | 1.4 ms | 0.4 / 1.1 / 1.7 ms | Pass |
| `wifi` | 19.5 / 30.3 / 38.0 ms | 5.4 ms | 2.3 / 4.2 / 5.0 ms | Pass |
| `4g` | 65.1 / 79.2 / 91.7 ms | 10.1 ms | 7.0 / 10.4 / 14.4 ms | Pass |
| `poor` | 166.2 / 379.2 / 413.0 ms | 27.4 ms | 15.8 / 29.9 / 32.7 ms | Pass |

Reaction time on `lan` (~14 ms) is mostly the server writing the new playback state to PostgreSQL before broadcasting.

Real browsers (`python -m scripts.browser_e2e`, two headless Edge devices, three runs): listener vs controller audio median 5–46 ms, worst sample 104 ms, 0–1 correction jumps while settled; pause stops both devices within 4–5 ms of each other.

**Conclusion:** the agreed tolerance (≤ 40 ms p95 on normal networks) is met with a wide margin (≤ 11 ms p95 on 4G), and even on a poor network the two listeners stay within 33 ms of each other. Network delay affects only how quickly a change is heard, never where in the song each device plays.

## Tuning decisions

| Setting | Value | Reasoning from the measurements |
| --- | --- | --- |
| `time_sync` probes on connect | 5, 200 ms apart | With 5 samples the best one is close to symmetric even on `poor` (clock error p95 27 ms); fewer samples raised the error on jittery links |
| Re-probe interval | 30 s | Device clocks drift a few ms per minute at most; frequent enough to absorb that, rare enough to cost nothing |
| Samples kept (`MAX_SAMPLES`) | 10 | Keeps a recent low-RTT sample while letting a stale one age out after a network change |
| `IN_SYNC_SECONDS` | 0.04 | Matches the sync tolerance; the clock estimate itself is well inside it on normal networks, so settle jumps converge |
| `RESYNC_SECONDS` | 0.15 | Above the worst clock error seen on `poor` (≤ 33 ms) plus browser `currentTime` jitter, so a settled player never re-jumps for noise |
| `SETTLE_MS` / `SETTLE_ATTEMPTS` | 750 ms / 3 | Lets the audio pipeline start before measuring; three learned jumps were always enough in browser runs |
| `DRIFT_TOLERANCE_SECONDS` | 0.5 | Acceptance limit (ROOM-05); reaction p95 is under it even on `poor` |

## Re-running

```bash
# API running (and `python -m scripts.seed` done)
python -m scripts.sync_benchmark http://127.0.0.1:8000            # all profiles
python -m scripts.sync_benchmark http://127.0.0.1:8000 4g poor    # some profiles
pytest tests/test_network_sync.py                                  # CI-sized run of all four profiles
python -m scripts.browser_e2e http://localhost:5173 http://localhost:8000
```

## Performance budgets (DATA + QA)

| Budget | Target (p95) | Measured | Evidence |
| --- | --- | --- | --- |
| Catalog search, 3+ characters, 50,000 songs | ≤ 25 ms | 4–8 ms | `python -m scripts.benchmark_catalog_rooms`; `tests/test_performance.py` |
| Catalog search, 1–2 characters, 50,000 songs | ≤ 100 ms | 51 ms | same (no trigram exists for 1–2 letters, so this is a scan of the pre-lowered `search_text`) |
| Room join (service + DB), rooms of 11 among 2,000 rooms / 20,000 participants | ≤ 50 ms | 15 ms | same |
| Room participant / membership lookups | index scan, < 5 ms | 0.04–0.12 ms | same (plan has no `Seq Scan`) |
| API reads under 10 concurrent users | ≤ 150 ms | 11–21 ms | `python -m scripts.perf_smoke` |
| API writes (log play) under 10 concurrent users | ≤ 200 ms | 25–39 ms | same |
| 9 users joining one room at the same instant | ≤ 300 ms | 162–181 ms | same (single API process: simultaneous joins queue) |
| Room broadcast to 9 listeners | ≤ 250 ms | 14 ms | same |
| Register / login (bcrypt by design) | ≤ 1500 ms | 0.6–1.1 s | same |

The API runs as one process because the room hub is in memory; requests that arrive in the same instant are handled one after another, which is why the burst-join budget is larger than the single-join budget.

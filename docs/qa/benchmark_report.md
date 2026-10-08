# Sync Latency and Drift Benchmark Report (RT, Phase 8)

Handbook Phase 8: "RT: Sync latency/drift benchmark report. Deliverable: benchmark report + rerunnable harness. Done when: report accepted by QA."

Release: **SoundSync 1.0.0** (WebSocket contract v1.4). Run 2026-10-07 on Windows 11, local API (one uvicorn process) + PostgreSQL 18 + Vite dev server, after every Phase 8 code change. Targets and tuning reasoning: [`../sync_tuning.md`](../sync_tuning.md).

## Result

**All sync and performance targets are met on every network profile and in real browsers.** Two listeners on a normal network (LAN, Wi-Fi, 4G) play at most 8.2 ms apart (p95; target 40 ms), and at most 27.4 ms apart on a poor network (target 150 ms). A controller's action reaches listeners in 91 ms p95 on 4G (target 250 ms). Real browsers kept the listener within 47 ms of the controller with no correction jumps once settled.

## Targets

| Measure | Normal networks (LAN, Wi-Fi, 4G) | Poor network |
| --- | --- | --- |
| Sync agreement: how far apart two listeners' audio plays (p95) | ≤ 40 ms | ≤ 150 ms |
| Reaction time: controller action → listener receives it (p95) | ≤ 250 ms | ≤ 500 ms |
| Real browsers: listener vs controller audio (max of 25 samples) | ≤ 150 ms, ≤ 1 correction jump once settled | — |
| Acceptance drift tolerance (ROOM-05) | 0.5 s | 0.5 s |

## Harness (rerunnable)

Run from `backend/` with the API running and `python -m scripts.seed` done. Every command prints PASS/FAIL per target and exits non-zero on failure.

| Command | What it measures | Time |
| --- | --- | --- |
| `python -m scripts.sync_benchmark http://127.0.0.1:8000` | 3 users in one room through a network simulator (`scripts/netem_proxy.py`) for each profile: reaction time, clock-estimate error, sync agreement | ~2 min |
| `python -m scripts.room_sync_check http://127.0.0.1:8000 20` | Room lifecycle, 20 rounds × 4 events × 3 clients, control transfer, drop/reconnect, admin leaving | ~30 s |
| `python -m scripts.browser_e2e http://localhost:5173 http://localhost:8000` | Two real headless Edge devices: listener vs controller `<audio>` position after song change, resume and control transfer | ~60 s |
| `python -m scripts.perf_smoke http://127.0.0.1:8000 10` | 10 concurrent users: API budgets and WebSocket broadcast | ~15 s |
| `python -m scripts.benchmark_catalog_rooms` | 50,000 songs, 2,000 rooms: search and room-join plans and timings (own throwaway data, removed afterwards) | ~1 min |
| `pytest tests/test_network_sync.py` | CI-sized run of all four network profiles (runs with every `pytest`) | ~40 s |

Network profiles (one-way delay, jitter, loss spikes): `lan` 1 ms ±0.5; `wifi` 10 ms ±5, 0.5% × +60 ms; `4g` 30 ms ±15, 1% × +120 ms; `poor` 75 ms ±40, 3% × +250 ms. Each listener's device clock is deliberately set up to ±3 s wrong.

## Results

### Network profiles (`sync_benchmark`)

| Profile | Round trip | Reaction p50 / p95 / max | Clock error p95 | Sync agreement p50 / p95 / max | Result |
| --- | --- | --- | --- | --- | --- |
| `lan` | ~2 ms | 16.2 / 19.5 / 35.6 ms | 1.0 ms | 0.3 / 0.9 / 1.5 ms | Pass |
| `wifi` | ~20 ± 10 ms | 25.4 / 32.7 / 36.7 ms | 4.5 ms | 2.7 / 5.1 / 6.0 ms | Pass |
| `4g` | ~60 ± 30 ms | 71.2 / 91.1 / 111.1 ms | 8.1 ms | 5.8 / 8.2 / 10.3 ms | Pass |
| `poor` | ~150 ± 80 ms | 164.0 / 380.5 / 422.4 ms | 23.3 ms | 15.2 / 27.4 / 32.9 ms | Pass |

### Real browsers (`browser_e2e`, three runs in a row)

Listener vs controller `<audio>` position, 25 samples 300 ms apart after the settle step:

| Run | After song change (median / p95 / max) | After resume | After control transfer | Jumps once settled | Pause gap |
| --- | --- | --- | --- | --- | --- |
| 1 | 20 / 24 / 24 ms | 18 / 22 / 23 ms | 2 / 21 / 22 ms | 0 | 0 ms |
| 2 | 23 / 28 / 28 ms | 8 / 28 / 28 ms | 4 / 20 / 21 ms | 0 | 3 ms |
| 3 | 20 / 21 / 21 ms | 30 / 46 / 47 ms | 2 / 18 / 20 ms | 0 | 0 ms |

All 30 steps passed in every run (auth, browse and play, room create and join by link, sync, control transfer, leave, admin upload/delete), each in about 61 s.

### Room engine (`room_sync_check`, `perf_smoke`)

| Check | Result |
| --- | --- |
| Playback delivery, 240 messages (20 rounds × 4 events × 3 clients) | p50 20.6 ms, p95 25.2 ms, max 29.1 ms (tolerance 500 ms): Pass |
| Room lifecycle, controller validation, transfer both ways, drop and reconnect, admin leaving | 13 / 13 Pass |
| WebSocket broadcast under 10 concurrent users (360 deliveries) | p50 16.7 ms, p95 21.6 ms (budget 250 ms): Pass |
| 9 users joining one room at the same instant | p95 125.6 ms (budget 300 ms): Pass |
| API reads / writes under 10 concurrent users | reads p95 46–124 ms (budget 150), log play p95 82.7 ms (budget 200), 0 errors: Pass |

### Database under load (`benchmark_catalog_rooms`)

| Check | Result |
| --- | --- |
| Search, 3+ characters, 50,000 songs | p95 2.3–7.6 ms (target 25 ms), trigram index used: Pass |
| Search, 1–2 characters | p95 4.0–33.2 ms (target 100 ms): Pass |
| Room join, rooms of 11 among 2,000 | p95 12.8 ms (target 50 ms): Pass |
| Participant and membership lookups | 0.016–0.090 ms, index scans only: Pass |

## Comparison with Phase 6

| Measure | Phase 6 | Phase 8 (1.0.0) | Change |
| --- | --- | --- | --- |
| Sync agreement p95: lan / wifi / 4g / poor | 1.1 / 4.2 / 10.4 / 29.9 ms | 0.9 / 5.1 / 8.2 / 27.4 ms | Same (within run-to-run noise) |
| Reaction p95: lan / wifi / 4g / poor | 17.8 / 30.3 / 79.2 / 379.2 ms | 19.5 / 32.7 / 91.1 / 380.5 ms | Same; a few ms from the per-room ordering lock (Phase 7), which guarantees no event is missed |
| Browser listener vs controller, worst sample | 104 ms, 0–1 jumps | 47 ms, 0 jumps | Better |
| Room join p95 (DB) | 15 ms | 12.8 ms | Same |

The Phase 7 ordering lock and the Phase 8 fix (deleting a playing song now stops the room for everyone, contract v1.4) did not cost any measurable sync quality.

## Harness defect found in this run

The first browser run failed at "join via the join link" three times out of three. The join link correctly uses `FRONTEND_BASE_URL`, which on this machine is the LAN address for phone testing, so the second browser opened a different origin where it was not logged in. The harness now checks that the link ends with `/room/{Room ID}` and opens that path on the app address it was given (defect D-20 in [`defect_log.md`](defect_log.md)). The app itself was not at fault.

## QA acceptance

| Lead | Team | Accepted | Date | Notes |
| --- | --- | --- | --- | --- |
| Eshwar (saladieshwar) | RT | Yes | 2026-10-07 | All targets met; harness rerunnable with the commands above |
| Eshwar (saladieshwar) | QA | Yes | 2026-10-07 | Report accepted: numbers reproduced in three browser runs and the full `pytest` (includes `test_network_sync.py`) |

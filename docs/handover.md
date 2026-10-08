# Knowledge Transfer and Handover (ALL, Phase 8)

Handbook Phase 8: "ALL: Knowledge transfer & handover. Deliverable: walkthrough notes + final source package. Done when: internal team can build/run/extend independently."

These are the walkthrough notes for the team taking over **SoundSync 1.0.0**. Read them top to bottom once; each section links to the detailed reference. Building and running from nothing is in [`setup_guide.md`](setup_guide.md); this page explains how the system fits together and how to change it safely.

## 1. What SoundSync is

A music web app: users register, browse and search a catalog, play songs in a footer player, keep liked songs and recently played, and listen **together** in a Musical Room where one controller drives playback for every device in sync. Admins upload songs and see users and active rooms.

| Part | Technology | Repository |
| --- | --- | --- |
| Frontend (FE) | React 19, Vite, Tailwind CSS 4, React Router, axios, Vitest | [`../../frontend`](../../frontend/README.md) |
| REST API (BE) | FastAPI, Pydantic 2, SQLAlchemy 2, JWT (PyJWT), bcrypt | `backend/app/api`, `services`, `repositories`, `schemas` |
| Room sync engine (RT) | FastAPI WebSockets, in-memory connection hub with a lock per room | `backend/app/realtime` |
| Data (DATA) | PostgreSQL 16+ (tested on 18) with `pg_trgm`, Alembic migrations, files under `media/` | `backend/app/models`, `alembic/`, `scripts/` |

## 2. Architecture

```text
 Browser (React SPA)                         FastAPI process (one process)
 ┌──────────────────────────┐   REST+JWT    ┌──────────────────────────────────────────┐
 │ pages → api/*.js (axios) ├──────────────►│ api/routes → services → repositories ──┐ │
 │ AuthContext, Library-    │               │        ▲                               │ │
 │ Context, PlayerContext   │  WebSocket    │ realtime/ws_routes → sync_facade ──────┤ │
 │ realtime/useRoomSocket   ├──────────────►│        connection_manager (in memory)  │ │
 │ realtime/serverClock     │◄── broadcast ─┤                                        ▼ │
 │ <audio> ◄── /media/... ──┼───────────────┤ StaticFiles /media      PostgreSQL ◄────┘ │
 └──────────────────────────┘               └──────────────────────────────────────────┘
```

Rules that keep it working:

- **Layers only call downwards**: route → service → repository → model. Routes hold no SQL; repositories hold no HTTP or business rules.
- **The database is the source of truth** for room playback. Every playback event is saved first, then broadcast with the saved state, so a reconnecting device just reads `room_state`.
- **One lock per room** (`manager.room_lock`) orders connect, playback and REST-triggered broadcasts, so a late joiner never misses an event ([`websocket_contract.md`](websocket_contract.md), ordering guarantees).
- **One API process**: the room hub lives in memory. Do not run several workers without first moving the hub to a shared broker (section 9).
- **Errors** are always `{"error": {"code", "message", "details"}}` with a code from `app/core/errors.py` ([`error_catalogue.md`](error_catalogue.md)).
- **No secrets in git or logs**: `.env` is ignored; JWTs in WebSocket URLs are redacted from every log line (`app/core/log_redaction.py`).

## 3. Repository map

Backend (`backend/`):

| Path | What lives there |
| --- | --- |
| `app/main.py` | App factory: settings, CORS, error handlers, `/media` static files, routers, version |
| `app/core/` | `config.py` (all settings, read from `.env`), `security.py` (bcrypt, JWT), `errors.py` (error codes), `log_redaction.py` |
| `app/api/routes/` | One module per area: `auth`, `songs`, `library`, `rooms`, `admin`, `health`; `deps.py` has the `DbSession`, `CurrentUser` and `AdminUser` dependencies |
| `app/services/` | Business rules: room lifecycle and playback state, uploads, likes and plays |
| `app/repositories/` | All SQL, one module per aggregate |
| `app/models/`, `app/schemas/` | SQLAlchemy tables and Pydantic request/response shapes |
| `app/realtime/` | `ws_routes.py` (socket endpoint), `events.py` (message types), `sync_facade.py` (what REST code may call), `connection_manager.py` (hub and locks) |
| `alembic/versions/` | Migrations `0001` to `0005` |
| `scripts/` | Seed, checks, backup restore, benchmarks, browser checks, release packaging |
| `tests/` | `pytest` suite; `live.py` starts a real server for WebSocket tests |
| `docs/` | Everything listed in [`documentation_checklist.md`](documentation_checklist.md) |

Frontend (`frontend/src/`):

| Path | What lives there |
| --- | --- |
| `App.jsx` | All routes |
| `api/` | One module per backend area; `client.js` adds the JWT and turns errors into readable messages |
| `context/` | `AuthContext` (session), `LibraryContext` (likes, recently played), `PlayerContext` (the single `<audio>`, queue, room-follow logic) |
| `realtime/` | `useRoomSocket` (connect, reconnect, clock probes), `serverClock` (server time estimate), `events.js` (message types, tuning constants, error texts) |
| `pages/`, `components/` | Screens and shared pieces (see [`ui_guide.md`](../../frontend/docs/ui_guide.md)) |

## 4. How a request flows

**REST (example: like a song).** `SongRow` calls `likeSong(id)` in `api/library.js` → axios adds `Authorization: Bearer <JWT>` → `POST /users/me/liked-songs/{id}` → `routes/library.py` (the `CurrentUser` dependency decodes the JWT) → `library_service.like_song` → `library_repo` → `liked_songs` row → `201`. `LibraryContext` updates `likedIds`, so every heart on screen changes at once.

**Room sync (example: controller presses pause).**

1. `RoomPage` → `PlayerContext` sends `{"type": "pause", "payload": {"position_seconds": 42.1}}` on the room socket.
2. `ws_routes.room_socket` validates the message, takes the room lock, and `room_service.apply_playback_event` checks the sender is the controller and saves `is_playing=false, position_seconds, state_updated_at`.
3. The saved state is broadcast to every socket in the room with `server_ts`.
4. Each listener's `PlayerContext` places audio at `position + (serverNow − server_ts)` using its `serverClock` estimate, then settles with at most a few small jumps. It never changes playback rate.

Details: [`websocket_contract.md`](websocket_contract.md) (messages, close codes, ordering, client steps) and [`sync_tuning.md`](sync_tuning.md) (why the numbers are what they are).

## 5. Data model

`users` 1—n `liked_songs` n—1 `songs`; `users` 1—n `recently_played` n—1 `songs`; `musical_rooms` (admin, controller, current song) 1—n `room_participants` n—1 `users`. Deleting a user removes their library rows and the rooms they own; deleting a song removes library rows and stops rooms playing it. Every rule is listed and proven in [`qa/data_checklist.md`](qa/data_checklist.md); tables, indexes and query rules are in [`schema.md`](schema.md).

## 6. How to extend

Each recipe ends with the check that proves it worked. Run `pytest` and `npm test` before every commit; `tests/test_docs.py` fails if the docs fall behind the code.

### Add a REST endpoint

1. Request/response models in `app/schemas/<area>.py`.
2. SQL in `app/repositories/<area>_repo.py`; rules in `app/services/<area>_service.py`.
3. Route in `app/api/routes/<area>.py` taking `user: CurrentUser` (or `AdminUser`) and `db: DbSession` from `app/api/deps.py`. A new module also needs `include_router` in `app/api/router.py`.
4. New error? Add the code to `ErrorCode` in `app/core/errors.py`, a row in `error_catalogue.md` and `qa/error_crosscheck.md`, and a message in the frontend if users can see it.
5. Test in `tests/test_<area>.py` with the `client` and `auth_headers` fixtures (each test is rolled back).
6. `python -m scripts.export_openapi`, then `pytest` (the OpenAPI snapshot test fails until you do).
7. Frontend: an exported function in `src/api/<area>.js`, listed in `ui_guide.md` ("REST (axios)").

### Change the database

1. Change the model in `app/models/`.
2. `alembic revision --autogenerate -m "short description"`, then read and fix the generated file (name it `0006_...` like the others).
3. `alembic upgrade head`, `alembic downgrade -1`, `alembic upgrade head` to prove both directions, then `alembic check` (no drift).
4. Index every new foreign key (`test_data_integrity::test_every_foreign_key_is_indexed_so_deletes_never_scan` fails otherwise) and add its delete rule to `qa/data_checklist.md` (checked by `test_data_integrity::test_delete_rules_match_in_database_models_and_checklist`).
5. Update `schema.md`; run `python -m scripts.check_db`.

### Add a room (WebSocket) event

1. Add it to `EventType` in `app/realtime/events.py`. Client-sent playback events go in `PLAYBACK_EVENTS`; server-only events must stay out of it.
2. Handle it in `ws_routes.py` inside `sync_facade.room_lock(room_id)` if it changes room state. REST code broadcasts only through `sync_facade` functions, scheduled with `BackgroundTasks` after the response.
3. Document it in `websocket_contract.md` (event table, payload, changelog row, version bump); `test_websocket_contract_lists_every_event_and_error_code` checks this.
4. Add a live test in `tests/test_room_sync.py` using the `peers` fixture (`expect`, `send` helpers from `tests/live.py`).
5. Frontend: add the type in `src/realtime/events.js` and handle it in `RoomPage.jsx` or `PlayerContext.jsx`; test in `RoomPage.test.jsx`.

### Add a page

1. Component in `src/pages/`; route in `src/App.jsx` inside `ProtectedRoute` (or `AdminRoute`).
2. Link it from `Navbar.jsx` if users should find it.
3. Add the route to `ui_guide.md` ("Screen and route list"; `test_every_frontend_route_is_in_the_ui_guide`).
4. Test with `renderWithRouter` from `src/testUtils.jsx`; add the screen to `scripts/ux_check.py` so it is checked at phone, tablet and desktop size.

### Add a setting

Add a field to `Settings` in `app/core/config.py`, a line in `.env.example` (placeholder value, never a real secret) and a row in `setup_guide.md`. `test_every_setting_is_in_env_example_and_setup_guide` enforces all three.

### Change sync behaviour

Change constants in `frontend/src/realtime/events.js` or logic in `PlayerContext.jsx`, then rerun `python -m scripts.sync_benchmark` and `python -m scripts.browser_e2e` and compare with [`qa/benchmark_report.md`](qa/benchmark_report.md). Update `sync_tuning.md` if a target or value changes.

## 7. Operations

| Task | Command or reference |
| --- | --- |
| Start locally | API `fastapi dev app/main.py`; frontend `npm run dev` ([`setup_guide.md`](setup_guide.md)) |
| Health | `GET /health` (process up), `GET /ready` (database up, else 503) |
| Seed or verify data | `python -m scripts.seed`, `python -m scripts.check_db` |
| Back up and restore | [`db_runbook.md`](db_runbook.md) sections 6–8; verify with `python -m scripts.restore_check` |
| Test on phones on the same Wi-Fi | [`../README.md`](../README.md), "Multi-device room testing" |
| Full release check | `pytest`, `npm test`, `npm run lint`, `npm run build`, `python -m scripts.browser_e2e`, `python -m scripts.ux_check` |
| Build the source package | `python -m scripts.package_release v1.0.0` (section 10) |

Production notes (HTTPS, a strong `JWT_SECRET_KEY`, `CORS_ORIGINS`, one worker, serving the frontend `dist/`) are in [`setup_guide.md`](setup_guide.md).

## 8. Quality gates already in place

- **240 backend tests** run against real PostgreSQL. Live-server tests open real WebSockets, network-profile tests simulate Wi-Fi, 4G and poor links, and docs tests keep the documentation true.
- **189 frontend tests** exercise the real providers, with a fake `<audio>` element and a fake WebSocket.
- **Browser scripts**: `browser_e2e` runs two real browsers through the whole product; `ux_check` checks every screen at three sizes.
- **QA records**:
  - [`qa/acceptance_matrix.md`](qa/acceptance_matrix.md): every acceptance case and result.
  - [`qa/defect_log.md`](qa/defect_log.md): defects with their evidence.
  - [`qa/uat_evidence_pack.md`](qa/uat_evidence_pack.md): Section 6 sign-off.

## 9. Known limits and next steps

| Limit | If you need more |
| --- | --- |
| One API process (room hub in memory) | Move presence and broadcasts to Redis pub/sub (or similar) behind `sync_facade`; nothing else calls the hub directly |
| Media files on local disk | Serve `media/` from object storage or a CDN; `mediaUrl()` in the frontend and `MEDIA_ROOT` / `MEDIA_URL_PREFIX` in the API are the only places that know |
| Phone browsers may block audio until the first tap | Already handled with **Tap to hear the room**; keep it when changing the room page |
| Wide admin tables scroll inside their box on phones | Card layout for phones if admins work on phones |

## 10. Final source package

Release **1.0.0** = both repositories at tag `v1.0.0` (branch `main`).

```powershell
# after both repos are merged to main
git tag v1.0.0; git push origin v1.0.0          # in backend/ and in frontend/
python -m scripts.package_release v1.0.0        # in backend/
```

This writes `backend/dist/soundsync-backend-1.0.0.zip`, `soundsync-frontend-1.0.0.zip` and `SHA256SUMS.txt`. The script packs only what git tracks and refuses to finish if a virtualenv, cache, `node_modules`, media, build output or `.env` gets in. Without a tag argument it packs the current working tree. To check a package, unzip it and follow [`setup_guide.md`](setup_guide.md) from step 1 (see "Handover verification" below).

## 11. Knowledge-transfer sessions

| # | Session (about 45 min each) | Walk through | Hands-on exercise |
| --- | --- | --- | --- |
| 1 | Build and run | Sections 1–3, `setup_guide.md` | Fresh clone → seed → log in as alice; run `pytest` and `npm test` |
| 2 | REST API and data | Sections 4–6, `schema.md`, `error_catalogue.md` | Add an endpoint with a test (recipe "Add a REST endpoint") |
| 3 | Room sync | `websocket_contract.md`, `sync_tuning.md` | Two browsers in one room; run `sync_benchmark`; read `PlayerContext` room-follow code |
| 4 | Frontend | `ui_guide.md`, `frontend/README.md` | Add a page and run `ux_check` |
| 5 | Operations and release | `db_runbook.md`, section 7 and 10 | Back up and restore with `restore_check`; build the source package |

## Handover verification (2026-10-07)

A check that someone holding only the source package and these docs can build, run and extend the system:

1. **Package.** `python -m scripts.package_release` produced `soundsync-backend-1.0.0.zip` (139 files) and `soundsync-frontend-1.0.0.zip` (80 files) with checksums, and reported no virtualenv, cache, media or `.env`.
2. **Build.** Both zips were unpacked into an empty folder next to each other. The only added file was a `.env` pointing at the existing database; it was deleted afterwards.
   - Backend: new virtualenv, `pip install -r requirements.txt`; `alembic current` showed `0005 (head)`; `python -m scripts.seed` ran, then `python -m scripts.check_db` printed 7 × OK.
   - Frontend: `npm ci`, `npm test` (189 passed), `npm run build` OK.
3. **Run.** The copy's API answered `/health`, `/ready` and `/docs` with 200.
4. **Extend.** The recipe "Add a REST endpoint" was followed in the copy to add `GET /songs/count`: a schema, a repository function, a route and a test.
   - The new test passed.
   - `test_openapi_snapshot_matches_the_code` then failed with "run python -m scripts.export_openapi", as the recipe says.
   - After the export, the full `pytest` passed: 241 tests, the 240 originals plus the new one. The live endpoint returned the song count.
5. The copy was deleted.

## Sign-off

| Lead | Team | Signed | Date | Notes |
| --- | --- | --- | --- | --- |
| Eshwar (saladieshwar) | BE | Yes | 2026-10-07 | API, services and operations walked through |
| Eshwar (saladieshwar) | RT | Yes | 2026-10-07 | Room engine, contract v1.4 and sync tuning walked through |
| Eshwar (saladieshwar) | DATA | Yes | 2026-10-07 | Schema, migrations, backup and restore walked through |
| Eshwar (saladieshwar) | FE | Yes | 2026-10-07 | Screens, contexts and realtime client walked through |
| Eshwar (saladieshwar) | QA | Yes | 2026-10-07 | Internal team can build, run and extend independently (verification above) |

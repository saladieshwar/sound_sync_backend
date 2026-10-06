# SoundSync Backend

FastAPI service covering three handbook stacks:

| Stack | Location |
| --- | --- |
| BE (REST API) | `app/api/`, `app/services/`, `app/repositories/`, `app/schemas/` |
| RT (room sync engine) | `app/realtime/` |
| DATA (PostgreSQL) | `app/models/`, `alembic/`, `scripts/` |

## Prerequisites

- Python 3.11+
- PostgreSQL 16+ (tested on 18)

## Local database bring-up

1. Create the app role and database (run once, as the `postgres` superuser). Pick a password for the `soundsync` role:

   ```powershell
   & "C:\Program Files\PostgreSQL\18\bin\psql.exe" -U postgres -h localhost -v app_password='your_password' -f scripts/setup_db.sql
   ```

   The script is idempotent: it creates the `soundsync` role and database if missing, resets the role password, and makes `soundsync` the database owner.

2. Configure the environment:

   ```powershell
   copy .env.example .env
   ```

   Set `DATABASE_URL=postgresql+psycopg://soundsync:your_password@localhost:5432/soundsync` and a long random `JWT_SECRET_KEY`. Special characters in the password must be URL-encoded (`@` → `%40`).

3. Install dependencies, migrate, and seed:

   ```powershell
   python -m venv venv
   .\venv\Scripts\activate
   pip install -r requirements.txt
   alembic upgrade head
   python -m scripts.seed
   ```

   Seed accounts: `admin@soundsync.dev` / `admin12345` (admin), `alice@soundsync.dev` / `alice12345`, `bob@soundsync.dev` / `bob1234567`.

   Seed catalog: 8 songs across 4 albums and 4 categories (`love`, `melody`, `motivation`, `sad`); album covers are generated into `media/covers/` and playable sample audio (WAV, ~14 MB total) into `media/audio/`. The seed is idempotent, so re-running it is safe. Migration `0003` creates the `pg_trgm` extension (trusted since PostgreSQL 13, so the database owner can create it).

4. Run and verify:

   ```powershell
   fastapi dev app/main.py
   ```

   - `GET http://localhost:8000/health` → `{"status": "ok"}`
   - `GET http://localhost:8000/ready` → `{"status": "ready", "database": "up"}`
   - Swagger UI: `http://localhost:8000/docs`

## Contracts

| Contract | Consumers | Location |
| --- | --- | --- |
| OpenAPI (REST) | FE, QA | Live at `/openapi.json`; snapshot in `docs/openapi.json` |
| WebSocket events | FE, BE, QA | `docs/websocket_contract.md` |
| Schema | BE, QA | `docs/schema.md`, `alembic/versions/` |
| Error catalogue | FE, QA | `docs/error_catalogue.md` |
| Acceptance matrix | All | `docs/qa/acceptance_matrix.md` |

Regenerate the OpenAPI snapshot after changing endpoints:

```powershell
python -m scripts.export_openapi
```

## Tests

```powershell
pytest
```

Tests run against PostgreSQL (`TEST_DATABASE_URL` if set, otherwise `DATABASE_URL`). Each test runs inside a transaction that is rolled back, so the database is left unchanged. `tests/test_auth.py` covers the Phase 2 auth cases and `tests/test_songs.py` / `tests/test_library.py` cover the Phase 3 catalog and library cases in `docs/qa/acceptance_matrix.md`. Catalog tests replace the `songs` table with the seed catalog inside the rolled-back transaction, so they do not depend on what is in your database. `tests/test_playback.py` covers Phase 4 (seed audio, media range requests, play logging, recently-played query plan).

Recently-played query benchmark (rolled back, leaves no data):

```powershell
python -m scripts.benchmark_recently_played 1000 200
```

Phase 5 (Musical Room): `tests/test_rooms.py` covers the room REST API and room tables inside the rolled-back transaction. `tests/test_room_sync.py` starts a real uvicorn server on a free port in a background thread and drives 2–3 WebSocket clients (play/pause/seek/song change, controller validation, control transfer both ways, leave, admin leave, drop/reconnect, malformed messages). Because the WebSocket route opens its own DB sessions, these tests commit data; every user and song they create is deleted when the module finishes.

Live multi-client check against a running API (prints delivery latency; cleans up its users):

```powershell
python -m scripts.room_sync_check http://127.0.0.1:8000 20
```

## Multi-device room testing (same Wi-Fi)

1. Find this machine's LAN IP (`ipconfig` → IPv4 Address, e.g. `192.168.1.20`).
2. In `.env`, set `FRONTEND_BASE_URL=http://192.168.1.20:5173` so join links open on other devices. In development, CORS already accepts private-LAN origins on port 5173 (`CORS_ORIGIN_REGEX` overrides this).
3. Start the API on all interfaces: `fastapi dev app/main.py --host 0.0.0.0` (or `uvicorn app.main:app --host 0.0.0.0 --port 8000`).
4. Start the frontend on all interfaces: `npm run dev -- --host` (in `frontend/`). With no `VITE_*` URLs set, the app calls the API on the same host it was opened from.
5. Allow Python and Node through Windows Defender Firewall for private networks if prompted.
6. Device A opens `http://192.168.1.20:5173`, creates a room, and shares the join link; device B opens the link (or types the Room ID) and taps **Join Room**. If a device shows **Tap to hear the room**, tap it once — browsers block audio until the user interacts with the page.

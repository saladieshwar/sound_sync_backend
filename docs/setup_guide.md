# Build, Configuration & API Reference (BE)

How to build and run SoundSync on a clean machine, every configuration setting, and where the API reference lives. Commands are for Windows PowerShell; on macOS/Linux use `source venv/bin/activate` and `cp` instead of `copy`.

## 1. What you need

| Tool | Version | Check |
| --- | --- | --- |
| Python | 3.11 or newer (tested 3.11.3) | `python --version` |
| PostgreSQL | 16 or newer (tested 18) | `psql --version` |
| Node.js | 20.19+ or 22.12+ (tested 22.20) — required by Vite 8 | `node --version` |
| npm | 10+ (tested 10.9) | `npm --version` |
| Git | any | `git --version` |

## 2. Get the code

The app is two repositories. Clone them side by side (docs link between them with `../backend` / `../frontend`):

```powershell
mkdir "Sound Sync"; cd "Sound Sync"
git clone https://github.com/saladieshwar/sound_sync_backend.git backend
git clone https://github.com/saladieshwar/sound_sync_frontend.git frontend
```

## 3. Backend: build and run

Run everything from `backend/`.

1. **Database** — create the role and database once, as the `postgres` superuser. Choose your own password for the `soundsync` role; it is only typed here and in `.env`:

   ```powershell
   & "C:\Program Files\PostgreSQL\18\bin\psql.exe" -U postgres -h localhost -v app_password='your_password' -f scripts/setup_db.sql
   ```

   Details, reset and backup/restore: [`db_runbook.md`](db_runbook.md).

2. **Configuration**:

   ```powershell
   copy .env.example .env
   python -c "import secrets; print(secrets.token_urlsafe(48))"
   ```

   In `.env`, put the password into `DATABASE_URL` and the printed value into `JWT_SECRET_KEY`. `.env` is git-ignored — never commit it. All settings are listed in section 5.

3. **Install, migrate, seed**:

   ```powershell
   python -m venv venv
   .\venv\Scripts\activate
   pip install -r requirements.txt
   alembic upgrade head
   python -m scripts.seed
   ```

4. **Run**:

   ```powershell
   fastapi dev app/main.py
   ```

5. **Verify**:

   | Check | Expected |
   | --- | --- |
   | `http://localhost:8000/health` | `{"status": "ok"}` |
   | `http://localhost:8000/ready` | `{"status": "ready", "database": "up"}` |
   | `http://localhost:8000/docs` | Swagger UI with auth, songs, library, rooms, admin |
   | `alembic current` | `0006 (head)` |
   | `python -m scripts.check_db` | every line `OK` |
   | `pytest` | all tests pass |

## 4. Frontend: build and run

From `frontend/`:

```powershell
npm ci
npm run dev        # http://localhost:5173
```

Open `http://localhost:5173`, register or log in with a seed account (`alice@soundsync.dev` / `alice12345`; admin: `admin@soundsync.dev` / `admin12345`).
Other commands: `npm test` (unit + journey tests), `npm run lint`, `npm run build` (production files in `dist/`). Screens and how the frontend talks to the API: [`../../frontend/docs/ui_guide.md`](../../frontend/docs/ui_guide.md).

## 5. Configuration reference

### Backend (`backend/.env`)

Read by `app/core/config.py`. Every setting has a default; `.env` overrides it.

| Variable | Default | What it does | When to change |
| --- | --- | --- | --- |
| `APP_NAME` | `SoundSync API` | Title in OpenAPI / Swagger | Rarely |
| `ENVIRONMENT` | `development` | Anything other than `development` refuses to start with a weak `JWT_SECRET_KEY` and turns off the LAN CORS rule | Set `production` on a real server |
| `DATABASE_URL` | `postgresql+psycopg://soundsync:soundsync@localhost:5432/soundsync` | PostgreSQL connection (psycopg 3 driver) | Always: your password; URL-encode special characters (`@` → `%40`) |
| `JWT_SECRET_KEY` | `change-me` | Signs login tokens (HS256) | Always: at least 32 random characters. Changing it logs everyone out |
| `JWT_ALGORITHM` | `HS256` | Token signing algorithm | Keep |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `60` | How long a login lasts | To shorten or lengthen sessions |
| `CORS_ORIGINS` | `http://localhost:5173` | Comma-separated frontend URLs allowed to call the API | Add every URL the frontend is served from |
| `CORS_ORIGIN_REGEX` | empty | Extra allowed origins as a regex. Empty in development = any private-LAN address on port 5173 | To allow other ports/hosts by pattern |
| `FRONTEND_BASE_URL` | `http://localhost:5173` | Base of shareable room join links (`…/room/{id}`) | Set to the address other devices use (LAN IP or public URL) |
| `MEDIA_ROOT` | `./media` | Folder for audio and cover files (seed + admin uploads) | To store media elsewhere; back it up with the database |
| `MEDIA_URL_PREFIX` | `/media` | URL path media is served from | Rarely; stored song URLs use it |
| `MAX_AUDIO_UPLOAD_BYTES` | `52428800` (50 MB) | Admin audio upload limit (`413 FILE_TOO_LARGE` above it) | To allow larger/smaller files |
| `MAX_COVER_UPLOAD_BYTES` | `5242880` (5 MB) | Image upload limit: admin song covers and profile pictures | Same |
| `CLOUDINARY_URL` | empty (uploads stay in `MEDIA_ROOT`) | `cloudinary://<api_key>:<api_secret>@<cloud_name>`; when set, uploaded songs, covers and avatars are stored on Cloudinary and their `https://res.cloudinary.com/…` URLs are saved | Required on Render's free plan, whose disk is wiped on every restart |
| `MEDIA_STORAGE` | empty: `database` when `ENVIRONMENT=production`, else `local` | Where uploads go when `CLOUDINARY_URL` is not set: `local` (files under `MEDIA_ROOT`) or `database` (the `media_files` table, served from the same `/media/…` URLs with range support) | Empty, so Render's free plan keeps uploads across restarts with no extra setup |
| `CLOUDINARY_FOLDER` | `soundsync` | Cloudinary folder that uploads go under (`<folder>/audio`, `/covers`, `/avatars`) | Same |

Test and tool settings (environment variables, not in `.env`):

| Variable | Used by | What it does |
| --- | --- | --- |
| `TEST_DATABASE_URL` | `pytest` | Run tests against another database (default: `DATABASE_URL`) |
| `BROWSER_PATH` | `scripts/browser_e2e.py` | Chrome/Edge executable for the two-browser test (default: Microsoft Edge) |

### Frontend (`frontend/.env`, optional)

| Variable | Default | What it does |
| --- | --- | --- |
| `VITE_API_BASE_URL` | `http://<page host>:8000` | REST API address |
| `VITE_WS_BASE_URL` | `VITE_API_BASE_URL` with `http` → `ws` | Room WebSocket address |

Vite bakes these in at build time: set them **before** `npm run build`. The dev server always uses port 5173 (`strictPort`), because that is the port the API's CORS settings expect.

## 6. Running on a server

- **One API process only.** Live room connections are kept in the API process's memory (`app/realtime/connection_manager.py`), so run a single worker: `uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1`. Two workers would split a room's listeners between processes.
- `ENVIRONMENT=production`, a strong `JWT_SECRET_KEY`, `CORS_ORIGINS` = the real frontend URL, `FRONTEND_BASE_URL` = the public frontend URL.
- Put HTTPS in front (e.g. nginx or Caddy) and forward WebSocket upgrades for `/rooms/{id}/ws`. Build the frontend with `VITE_API_BASE_URL=https://…` and `VITE_WS_BASE_URL=wss://…`; browsers block `ws://` from an `https://` page.
- Serve `frontend/dist/` as static files with a fallback to `index.html` (client-side routes like `/room/ABCD2345`).
- Keep `MEDIA_ROOT` on persistent storage and include it in backups ([`db_runbook.md`](db_runbook.md)).
- Logs never contain passwords or JWTs (room socket URLs are written as `token=[redacted]`).

### Hosted: MusicPartner (Render + Vercel)

The public site is the frontend on Vercel (project `musicpartner`, `https://musicpartner.vercel.app`) talking to the API on Render. Vercel cannot run the API: it has no WebSockets, no long-running process and no disk.

1. **API and database (Render).** On render.com: **New → Blueprint**, pick the backend repository and apply. [`render.yaml`](../render.yaml) creates the `musicpartner-api` web service and the `musicpartner-db` PostgreSQL database, generates `JWT_SECRET_KEY`, and on every start runs `alembic upgrade head`, `python -m scripts.seed --catalog-only` (demo songs, no seed accounts) and uvicorn. A `postgres://` / `postgresql://` `DATABASE_URL` is switched to the psycopg driver automatically.
2. **Frontend (Vercel).** On vercel.com: **Add New → Project**, import the frontend repository, name it `musicpartner`, add `VITE_API_BASE_URL` = the Render service URL (e.g. `https://musicpartner-api.onrender.com`) and deploy. [`vercel.json`](../../frontend/vercel.json) sends every route to `index.html`. `VITE_WS_BASE_URL` is derived (`https` → `wss`).
3. If Vercel gives a different address, set `CORS_ORIGINS` and `FRONTEND_BASE_URL` on Render to it.
4. **First admin.** Register on the site, then from `backend/` run, with the database's **External Database URL** from Render: `$env:DATABASE_URL = "<external URL>"; python -m scripts.make_admin you@example.com`. Close that terminal afterwards so the URL is not reused.

Free-plan limits: the API sleeps after 15 minutes without traffic (the first request then takes about a minute), the disk is wiped on every restart or deploy (songs and pictures uploaded by the admin are lost; the demo catalog is regenerated), and the free database expires after 30 days. A paid instance with a persistent disk mounted at `MEDIA_ROOT` removes the first two.

## 7. API reference

| What | Where |
| --- | --- |
| REST API (all endpoints, request/response shapes, error responses) | Live: `http://localhost:8000/docs` (Swagger UI) and `/openapi.json`. Snapshot: [`openapi.json`](openapi.json) |
| Error codes and example requests | [`error_catalogue.md`](error_catalogue.md) |
| Room WebSocket messages | [`websocket_contract.md`](websocket_contract.md) |
| Database schema | [`schema.md`](schema.md) |

The snapshot is final for this release: `tests/test_docs.py` fails if `docs/openapi.json` differs from the running code. After changing an endpoint, regenerate it with `python -m scripts.export_openapi`.

Endpoints at a glance:

| Area | Access | Endpoints |
| --- | --- | --- |
| Health | Public | `GET /health`, `GET /ready` |
| Auth | Public; `/auth/me` needs a token | `POST /auth/register`, `POST /auth/login`, `GET /auth/me` |
| Catalog | Public | `GET /songs`, `/songs/search?q=`, `/songs/categories`, `/songs/category/{name}`, `/songs/albums`, `/songs/album/{name}`, `/songs/{id}`; media files under `/media/…` |
| Profile | Login token | `PATCH /users/me`, `PUT`/`DELETE /users/me/avatar` |
| Library | Login token | `GET /users/me/liked-songs`, `POST`/`DELETE /users/me/liked-songs/{song_id}`, `GET /users/me/recently-played`, `POST /users/me/recently-played/{song_id}` |
| Rooms | Login token | `POST /rooms`, `GET /rooms/{id}`, `POST /rooms/{id}/join`, `POST /rooms/{id}/leave`, `POST /rooms/{id}/transfer-access`; WebSocket `/rooms/{id}/ws?token=` |
| Admin | Admin token | `POST /admin/songs`, `PATCH /admin/songs/{id}`, `PUT`/`DELETE /admin/songs/{id}/cover`, `DELETE /admin/songs/{id}`, `GET /admin/users`, `GET /admin/rooms` |

## 8. Troubleshooting

| Symptom | Cause and fix |
| --- | --- |
| `password authentication failed for user "soundsync"` | Password in `DATABASE_URL` differs from the one given to `setup_db.sql`, or a special character is not URL-encoded |
| `permission denied to create extension "pg_trgm"` during `alembic upgrade` | The `soundsync` role does not own the database — re-run `scripts/setup_db.sql` |
| `/ready` returns 503 | PostgreSQL is not running or `DATABASE_URL` is wrong |
| API refuses to start: `JWT_SECRET_KEY must be …` | `ENVIRONMENT` is not `development` and the secret is a placeholder or shorter than 32 characters |
| Browser console shows a CORS error | The page's URL (scheme + host + port) is not in `CORS_ORIGINS` |
| `npm run dev` says port 5173 is in use | Another dev server is running; stop it (the port is fixed on purpose) |
| Room page shows "Reconnecting…" forever | API not reachable on `VITE_WS_BASE_URL`, or a proxy does not forward WebSocket upgrades |
| Phone joins a room but hears nothing | Browsers block audio until a tap: press **Tap to hear the room** once |
| Songs list is empty | Seed not run: `python -m scripts.seed` |

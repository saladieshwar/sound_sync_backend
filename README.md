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
| Acceptance matrix | All | `docs/qa/acceptance_matrix.md` |

Regenerate the OpenAPI snapshot after changing endpoints:

```powershell
python -m scripts.export_openapi
```

## Tests

```powershell
pytest
```

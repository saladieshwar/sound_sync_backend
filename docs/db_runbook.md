# Database Runbook (DATA)

How to create, migrate, seed, check, reset, back up and restore the SoundSync database, and how QA recreates the test fixtures. Schema details: [`schema.md`](schema.md).

Commands run from `backend/` with the virtual environment active. `psql`, `pg_dump`, `pg_restore`, `initdb` and `pg_ctl` live in `C:\Program Files\PostgreSQL\18\bin\` on Windows; add that folder to `PATH` or type the full path. They ask for the `soundsync` password when needed. Never put real passwords in files, scripts or commits.

## What makes up "the data"

| Part | Where | Restored by |
| --- | --- | --- |
| Tables (users, songs, likes, plays, rooms, participants) | PostgreSQL database `soundsync` | `pg_restore` |
| Audio and cover files (seed + admin uploads) | `MEDIA_ROOT` folder (default `backend/media/`) | copying the folder back |

Songs store URLs like `/media/audio/<file>`, so the database and the media folder must be backed up and restored **together**.

## 1. First-time setup

1. **Role and database** (once, as the `postgres` superuser):

   ```powershell
   psql -U postgres -h localhost -v app_password='your_password' -f scripts/setup_db.sql
   ```

   Creates the `soundsync` login role and the `soundsync` database owned by it. Safe to re-run (it also resets the role's password). The role needs no superuser rights: it owns the database, so it can create the `pg_trgm` extension (a trusted extension since PostgreSQL 13).

2. **Connection**: in `.env`, `DATABASE_URL=postgresql+psycopg://soundsync:your_password@localhost:5432/soundsync` (URL-encode special characters).

3. **Schema**: `alembic upgrade head`. This creates all six tables, the indexes and `pg_trgm` (migrations `0001`–`0005`, listed in [`schema.md`](schema.md)).

4. **Seed data**: `python -m scripts.seed` (details in section 3).

5. **Check**: `python -m scripts.check_db`. Every line must say `OK`:

   ```text
   OK    database connection
   OK    migration at head: current 0005, head 0005
   OK    pg_trgm extension: installed
   OK    tables: 6 present
   OK    seed accounts: 3 present
   OK    seed catalog: 8 songs match
   OK    seed media files: present under ./media
   ```

## 2. Migrations

| Task | Command |
| --- | --- |
| Show the database's version | `alembic current` |
| Upgrade to the latest | `alembic upgrade head` |
| Go back one step | `alembic downgrade -1` |
| Check models and migrations agree | `alembic check` (must print "No new upgrade operations detected") |
| Add a migration (DATA only) | `alembic revision -m "short description"`, write `upgrade()` and `downgrade()`, update [`schema.md`](schema.md) |

Every migration has a working `downgrade()`. Upgrade the database whenever you pull new code with a new file in `alembic/versions/`.

## 3. Seed fixtures

`python -m scripts.seed` is **idempotent**: users are matched by email and songs by title + artist, so re-running it fixes changed rows without creating duplicates. It also writes the media files.

Accounts:

| Email | Password | Role |
| --- | --- | --- |
| `admin@soundsync.dev` | `admin12345` | admin |
| `alice@soundsync.dev` | `alice12345` | user |
| `bob@soundsync.dev` | `bob1234567` | user |

These are public development fixtures, not real credentials. Do not run the seed on a production database (or change these passwords right after).

Catalog (8 songs, 4 albums, 4 categories). Audio is generated WAV, exactly `duration_seconds` long, in `media/audio/<title-slug>.wav`; album covers are SVG in `media/covers/<album-slug>.svg`:

| Title | Artist | Album | Category | Seconds |
| --- | --- | --- | --- | --- |
| Evening Breeze | Aria Nova | Calm Skies | melody | 214 |
| Moonlit Path | Aria Nova | Calm Skies | melody | 198 |
| Heartstrings | The Lovelines | Forever Yours | love | 231 |
| Only You | The Lovelines | Forever Yours | love | 205 |
| Rise Up | Peak Drive | Unstoppable | motivation | 187 |
| Keep Going | Peak Drive | Unstoppable | motivation | 176 |
| Grey Rain | Blue Hours | Quiet Rooms | sad | 242 |
| Letters Unsent | Blue Hours | Quiet Rooms | sad | 219 |

Expected results on a freshly seeded database (songs uploaded later through the admin panel add more categories and albums):

| Request | Expected |
| --- | --- |
| `GET /songs/search?q=rain` | Grey Rain |
| `GET /songs/search?q=aria` | Evening Breeze, Moonlit Path (artist match) |
| `GET /songs/search?q=zzz` | `[]` |
| `GET /songs/category/sad` (any letter case) | Grey Rain, Letters Unsent |
| `GET /songs/categories` | `love`, `melody`, `motivation`, `sad` |
| `GET /songs/albums` | 4 albums, 2 songs each |
| `GET /songs/album/Calm Skies` | Evening Breeze, Moonlit Path |
| `GET /admin/rooms` with a fresh seed | `[]` (no rooms) |

## 4. How the automated tests use the database

- `pytest` uses `TEST_DATABASE_URL` if set, otherwise `DATABASE_URL`. The database must be at `alembic upgrade head`; it does not need to be seeded.
- Most tests run inside a transaction that is **rolled back**, so they leave nothing behind. The `catalog` fixture replaces the `songs` table with exactly the seed catalog *inside* that transaction, so catalog tests give the same results on any database.
- Live-server tests (`test_room_sync.py`, `test_e2e.py`, `test_network_sync.py`) must commit, because the WebSocket route opens its own sessions. They create users with random `@soundsync.dev` emails and delete them (and their rooms, likes and plays, by cascade) when they finish.
- Benchmarks (`scripts/benchmark_*.py`) insert their data in a transaction and roll it back.

To keep tests away from your dev data, create a second database (as `postgres`: `CREATE DATABASE soundsync_test OWNER soundsync;`), run `alembic upgrade head` against it, and set `TEST_DATABASE_URL` for the test command only.

## 5. Reset a development database

Removes **all** data, then rebuilds the schema and the seed. Stop the API first.

```powershell
alembic downgrade base
alembic upgrade head
python -m scripts.seed
python -m scripts.check_db
```

Uploaded media files are not deleted; remove anything in `media/audio` and `media/covers` that the seed did not create if you want a clean folder.

## 6. Backup

Make a backups folder outside the repository, or `backend/backups/` (git-ignored). Then back up the database **and** the media folder at the same time:

```powershell
$stamp = Get-Date -Format "yyyy-MM-dd_HHmm"
pg_dump -U soundsync -h localhost -d soundsync --format=custom --file "backups\soundsync_$stamp.dump"
Compress-Archive -Path media\* -DestinationPath "backups\media_$stamp.zip"
pg_restore --list "backups\soundsync_$stamp.dump" | Select-Object -First 5
```

`--format=custom` is compressed and lets `pg_restore` pick objects. The last line proves the file is a readable backup. The API can keep running during `pg_dump` (it takes a consistent snapshot).

## 7. Restore

Stop the API before restoring (open connections block `--clean` and would see half-restored data).

**A. Over the existing database** (roll back to a backup):

```powershell
pg_restore -U soundsync -h localhost -d soundsync --clean --if-exists --no-owner --single-transaction "backups\soundsync_<stamp>.dump"
Remove-Item media -Recurse -Force; Expand-Archive "backups\media_<stamp>.zip" -DestinationPath media
python -m scripts.check_db
```

`--single-transaction` means a failed restore changes nothing.

**B. Onto a new machine or empty server**:

1. Run section 1 step 1 (`setup_db.sql`) to create the role and an empty database.
2. Restore. No `alembic upgrade` is needed, because the dump already contains the tables and the `alembic_version` row:

   ```powershell
   pg_restore -U soundsync -h localhost -d soundsync --no-owner --single-transaction "backups\soundsync_<stamp>.dump"
   Expand-Archive "backups\media_<stamp>.zip" -DestinationPath media
   ```

3. Run `alembic upgrade head` in case the code is newer than the backup, then `python -m scripts.check_db`.

## 8. Prove a backup restores (restore check)

`python -m scripts.restore_check <target>` runs sections 6 and 7 end to end and compares the result with the source. The source database is only read.

1. It backs up the `DATABASE_URL` database and zips `MEDIA_ROOT`.
2. It restores into `<target>`, which must be an **empty** database owned by `soundsync`.
3. It restores a second time over the copy with `--clean`.
4. After each restore it compares every table's row count and data checksum, indexes, constraints, sequences, extensions and migration version. It also runs `check_db` and `alembic check` on the copy, and compares the media files byte for byte.

Every line must say `OK`, ending in `PASS`.

`<target>` can be:

- **A database name on the same server.** Have the `postgres` superuser run `CREATE DATABASE soundsync_restore_check OWNER soundsync;` once, then:

  ```powershell
  python -m scripts.restore_check soundsync_restore_check --drop
  ```

  `--drop` deletes the scratch database afterwards.

- **A full URL to another PostgreSQL server**, set up with section 1 step 1. This is the "new machine" case:

  ```powershell
  python -m scripts.restore_check postgresql+psycopg://soundsync@127.0.0.1:5499/soundsync
  ```

To test without anyone's superuser password, create a throwaway server owned by your Windows user, and delete it afterwards:

```powershell
$data = "$env:TEMP\soundsync_pgtest"
initdb -D $data -U postgres --auth=trust -E UTF8
pg_ctl -D $data -o "-p 5499 -c listen_addresses=127.0.0.1" -l "$data\server.log" -w start
psql -U postgres -h 127.0.0.1 -p 5499 -v app_password='any_value' -f scripts/setup_db.sql
python -m scripts.restore_check postgresql+psycopg://soundsync@127.0.0.1:5499/soundsync
pg_ctl -D $data -m fast -w stop; Remove-Item $data -Recurse -Force
```

**Verified on PostgreSQL 18 (2026-10-07)** using a throwaway server as above. That server was a fresh install with a `soundsync` role that has no superuser or create-database rights, exactly as `setup_db.sql` makes it.

| Check | Result |
| --- | --- |
| Backup | 76-entry archive; 16 media files identical after the zip round trip |
| Restore into an empty database (section 7B) | 7 tables / 54 rows with identical data checksums; 23 indexes, 51 constraints, 3 sequences and 2 extensions (`plpgsql`, `pg_trgm`) identical; migration `0005`; `check_db` all OK; `alembic check` no drift |
| Restore over the existing copy with `--clean` (section 7A) | Identical again |
| Source database | Unchanged |
| Full backend test suite (`pytest`) on the restored copy | 220 passed |
| Reset path (section 5) on that server | `alembic downgrade base`, `upgrade head`, `seed`, `check_db` all OK, `alembic check` no drift |

## 9. Quick reference

| Goal | Command |
| --- | --- |
| Is the database ready? | `python -m scripts.check_db` |
| Version | `alembic current` |
| Upgrade | `alembic upgrade head` |
| Seed or repair fixtures | `python -m scripts.seed` |
| Full reset | `alembic downgrade base; alembic upgrade head; python -m scripts.seed` |
| Backup | `pg_dump -U soundsync -h localhost -d soundsync -Fc -f <file>.dump` + zip `media` |
| Restore | `pg_restore -U soundsync -h localhost -d soundsync --clean --if-exists --no-owner --single-transaction <file>.dump` + unzip `media` |
| Prove a backup restores | `python -m scripts.restore_check <empty database name or URL>` |

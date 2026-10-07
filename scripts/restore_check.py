"""Full backup/restore check. Run from backend/: python -m scripts.restore_check <target>

<target> is an empty database owned by the app role, either a database name on the same server
(created once by the postgres superuser: CREATE DATABASE soundsync_restore_check OWNER soundsync;)
or a full URL to another server, e.g. a fresh PostgreSQL set up with scripts/setup_db.sql:
    postgresql+psycopg://soundsync@127.0.0.1:5499/soundsync

Steps (the source database is only read):
  1. pg_dump the DATABASE_URL database (custom format) and zip MEDIA_ROOT, as in docs/db_runbook.md.
  2. pg_restore into the empty scratch database; unzip the media into a temp folder.
  3. Compare source and copy: every table's row count and data checksum, indexes, constraints,
     sequences, extensions, alembic version; media files byte for byte.
  4. Run scripts.check_db and `alembic check` against the copy (with the unzipped media).
  5. Restore again over the copy with --clean --if-exists (the "roll back to a backup" path); compare again.
Prints OK/FAIL lines; exits 1 on any failure. Passwords are passed only through the child
processes' environment. --drop removes the scratch database at the end.
"""

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL, make_url

from app.core.config import settings

BACKEND_DIR = Path(__file__).resolve().parent.parent
_DEFAULT_PG_BIN = Path(r"C:\Program Files\PostgreSQL\18\bin")


def _pg_tool(name: str) -> str:
    found = shutil.which(name, path=os.getenv("PG_BIN")) or shutil.which(name)
    if found:
        return found
    candidate = _DEFAULT_PG_BIN / f"{name}.exe"
    if candidate.is_file():
        return str(candidate)
    sys.exit(f"{name} not found: add PostgreSQL's bin folder to PATH or set PG_BIN")


def _pg_args(url: URL) -> list[str]:
    return ["-U", url.username, "-h", url.host or "localhost", "-p", str(url.port or 5432), "-d", url.database]


def _run(cmd: list[str], url: URL, extra_env: dict | None = None) -> subprocess.CompletedProcess:
    env = {**os.environ, "PGPASSWORD": url.password or "", **(extra_env or {})}
    return subprocess.run(cmd, env=env, capture_output=True, text=True, cwd=BACKEND_DIR)


def snapshot(url: URL) -> dict:
    """Everything a restore must reproduce, read with plain SQL."""
    engine = create_engine(url)
    try:
        with engine.connect() as c:
            # Same text form of every row on any server, whatever its locale or time zone.
            c.execute(text("SET TimeZone = 'UTC'; SET DateStyle = 'ISO, YMD'; SET extra_float_digits = 1"))
            tables = c.execute(text(
                "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename"
            )).scalars().all()
            data = {}
            for table in tables:
                count, digest = c.execute(text(
                    f'SELECT count(*), md5(coalesce(string_agg(t::text, \'|\' ORDER BY t::text COLLATE "C"), \'\')) '
                    f'FROM "{table}" t'
                )).one()
                data[table] = (count, digest)
            return {
                "tables": data,
                "indexes": c.execute(text(
                    "SELECT indexname, indexdef FROM pg_indexes WHERE schemaname = 'public' ORDER BY 1"
                )).all(),
                "constraints": c.execute(text(
                    "SELECT conrelid::regclass::text, conname, pg_get_constraintdef(oid) FROM pg_constraint "
                    "WHERE connamespace = 'public'::regnamespace ORDER BY 1, 2"
                )).all(),
                "sequences": c.execute(text(
                    "SELECT sequencename, last_value FROM pg_sequences WHERE schemaname = 'public' ORDER BY 1"
                )).all(),
                "extensions": c.execute(text(
                    "SELECT extname FROM pg_extension ORDER BY 1"
                )).scalars().all(),
                "alembic": c.execute(text("SELECT version_num FROM alembic_version")).scalar(),
            }
    finally:
        engine.dispose()


def _is_empty(url: URL) -> bool:
    engine = create_engine(url)
    try:
        with engine.connect() as c:
            return not c.execute(text("SELECT 1 FROM pg_tables WHERE schemaname = 'public'")).first()
    finally:
        engine.dispose()


def _files(root: Path) -> dict[str, str]:
    return {
        p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob("*")) if p.is_file()
    }


class Report:
    def __init__(self) -> None:
        self.failed: list[str] = []

    def check(self, name: str, passed: bool, detail: str = "") -> None:
        print(f"{'OK  ' if passed else 'FAIL'}  {name}{': ' + detail if detail else ''}")
        if not passed:
            self.failed.append(name)

    def compare(self, label: str, source: dict, copy: dict) -> None:
        for key in ("tables", "indexes", "constraints", "sequences", "extensions", "alembic"):
            same = source[key] == copy[key]
            detail = ""
            if key == "tables":
                rows = sum(count for count, _ in source[key].values())
                detail = f"{len(source[key])} tables, {rows} rows, checksums {'equal' if same else 'DIFFER'}"
                if not same:
                    detail += f" {[t for t in source[key] if source[key][t] != copy[key].get(t)]}"
            elif key == "alembic":
                detail = f"{source[key]} -> {copy[key]}"
            else:
                detail = f"{len(source[key])} {'equal' if same else 'DIFFER'}"
            self.check(f"{label}: {key}", same, detail)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("target", help="empty database: a name on the same server, or a full URL")
    parser.add_argument("--drop", action="store_true", help="drop the target database afterwards (same server only)")
    args = parser.parse_args()

    source = make_url(settings.DATABASE_URL)
    same_server = "://" not in args.target
    target = source.set(database=args.target) if same_server else make_url(args.target)
    if (target.host, target.port, target.database) == (source.host, source.port, source.database):
        sys.exit("target database must differ from the source database")
    if args.drop and not same_server:
        sys.exit("--drop only works for a database on the same server")

    report = Report()
    work = Path(tempfile.mkdtemp(prefix="soundsync_restore_"))
    try:
        if not _is_empty(target):
            sys.exit(f"{target.database} is not empty; recreate it or drop its tables first")

        dump = work / "soundsync.dump"
        result = _run([_pg_tool("pg_dump"), *_pg_args(source), "--format=custom", "--file", str(dump)], source)
        report.check("backup: pg_dump", result.returncode == 0 and dump.is_file(),
                     f"{dump.stat().st_size} bytes" if dump.is_file() else result.stderr.strip()[:200])
        listing = _run([_pg_tool("pg_restore"), "--list", str(dump)], source)
        report.check("backup: archive readable", listing.returncode == 0,
                     f"{len(listing.stdout.splitlines())} entries")

        media_root = (BACKEND_DIR / settings.MEDIA_ROOT).resolve()
        media_zip = work / "media.zip"
        with zipfile.ZipFile(media_zip, "w", zipfile.ZIP_DEFLATED) as zf:
            for path in sorted(media_root.rglob("*")):
                if path.is_file():
                    zf.write(path, path.relative_to(media_root).as_posix())
        restored_media = work / "media"
        with zipfile.ZipFile(media_zip) as zf:
            zf.extractall(restored_media)
        source_files = _files(media_root)
        report.check("backup: media zip round trip", _files(restored_media) == source_files,
                     f"{len(source_files)} files identical")

        before = snapshot(source)
        restore = [_pg_tool("pg_restore"), *_pg_args(target), "--no-owner", "--single-transaction"]

        result = _run([*restore, str(dump)], target)
        report.check("restore into empty database", result.returncode == 0, result.stderr.strip()[:300])
        report.compare("empty restore", before, snapshot(target))

        child_env = {"DATABASE_URL": target.render_as_string(hide_password=False), "MEDIA_ROOT": str(restored_media)}
        check = _run([sys.executable, "-m", "scripts.check_db"], target, child_env)
        report.check("check_db on the copy", check.returncode == 0,
                     "all OK" if check.returncode == 0 else check.stdout.strip())
        drift = _run([sys.executable, "-m", "alembic", "check"], target, child_env)
        report.check("alembic check on the copy", drift.returncode == 0,
                     "no drift" if drift.returncode == 0 else (drift.stdout + drift.stderr).strip()[-300:])

        result = _run([*restore, "--clean", "--if-exists", str(dump)], target)
        report.check("restore over existing database (--clean)", result.returncode == 0, result.stderr.strip()[:300])
        report.compare("clean restore", before, snapshot(target))

        report.check("source database unchanged", snapshot(source) == before)
    finally:
        shutil.rmtree(work, ignore_errors=True)
        if args.drop:
            engine = create_engine(source, isolation_level="AUTOCOMMIT")
            try:
                with engine.connect() as c:
                    c.execute(text(f'DROP DATABASE IF EXISTS "{target.database}" WITH (FORCE)'))
                print(f"Dropped {target.database}")
            finally:
                engine.dispose()

    print("PASS" if not report.failed else f"FAILED: {report.failed}")
    return 1 if report.failed else 0


if __name__ == "__main__":
    sys.exit(main())

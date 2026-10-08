"""Build the final source package: one zip per repository plus SHA256SUMS.txt, in backend/dist/.

    python -m scripts.package_release            # working tree: tracked + new files git would commit
    python -m scripts.package_release v1.0.0     # an exact tag or commit (both repos)

Only files git would ship are packed (`.gitignore` applies), so virtualenvs, node_modules, media,
backups, build output and `.env` never enter the package; the script fails if one ever does. It also
fails when the API version and the frontend package version differ.
"""

import hashlib
import json
import re
import subprocess
import sys
import zipfile
from pathlib import Path, PurePosixPath

from app.main import app

BACKEND = Path(__file__).resolve().parent.parent
FRONTEND = BACKEND.parent / "frontend"
DIST = BACKEND / "dist"
FORBIDDEN_DIRS = {"venv", ".venv", "__pycache__", "node_modules", ".pytest_cache", "media", "backups", "dist"}
SECRET_FILE = re.compile(r"^\.env(\..+)?$")


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout


def forbidden(name: str) -> str | None:
    """Why `name` (a path inside the package) must not ship, or None."""
    path = PurePosixPath(name)
    for part in path.parts[:-1]:
        if part in FORBIDDEN_DIRS:
            return f"{part}/ directory"
    if SECRET_FILE.match(path.name) and path.name != ".env.example":
        return "environment file (secrets)"
    if path.suffix == ".pyc":
        return "compiled Python"
    return None


def _pack(repo: Path, label: str, version: str, ref: str | None) -> Path:
    out = DIST / f"soundsync-{label}-{version}.zip"
    prefix = f"soundsync-{label}-{version}/"
    if ref:
        _git(repo, "archive", "--format=zip", f"--prefix={prefix}", "-o", str(out), ref)
    else:
        files = _git(repo, "ls-files", "--cached", "--others", "--exclude-standard", "-z").split("\0")
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
            for name in sorted(f for f in files if f and (repo / f).is_file()):
                zf.write(repo / name, prefix + name)
    with zipfile.ZipFile(out) as zf:
        names = [n.removeprefix(prefix) for n in zf.namelist() if not n.endswith("/")]
    bad = [f"{n}: {why}" for n in names if (why := forbidden(n))]
    if bad:
        out.unlink()
        raise SystemExit(f"{label}: refusing to package\n  " + "\n  ".join(bad))
    print(f"  {out.name}: {len(names)} files, {out.stat().st_size / 1024:.0f} KB")
    return out


def main() -> None:
    ref = sys.argv[1] if len(sys.argv) > 1 else None
    if not (FRONTEND / "package.json").is_file():
        raise SystemExit(f"frontend repo not found at {FRONTEND}")
    version = app.version
    fe_version = json.loads((FRONTEND / "package.json").read_text(encoding="utf-8"))["version"]
    if fe_version != version:
        raise SystemExit(f"version mismatch: API {version}, frontend {fe_version}")

    DIST.mkdir(exist_ok=True)
    print(f"SoundSync {version} source package ({ref or 'working tree'})")
    packages = [_pack(BACKEND, "backend", version, ref), _pack(FRONTEND, "frontend", version, ref)]
    sums = "".join(f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}\n" for p in packages)
    (DIST / "SHA256SUMS.txt").write_text(sums, encoding="utf-8")
    print(f"  SHA256SUMS.txt\nPASS: no virtualenv, cache, media, build output or .env in the package -> {DIST}")


if __name__ == "__main__":
    main()

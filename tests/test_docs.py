"""Phase 7 documentation pack: the docs must stay true to the code.

Fails when an error code, event, setting, route, script, test name or link in the docs no longer
matches the code. Frontend checks need the frontend repo cloned next to this one (skipped otherwise).
"""

import ast
import json
import re
from pathlib import Path

import pytest

from app.core.config import Settings
from app.core.errors import ErrorCode
from app.main import app
from app.realtime.events import WS_ERROR_CODES, EventType

BACKEND = Path(__file__).resolve().parent.parent
DOCS = BACKEND / "docs"
FRONTEND = BACKEND.parent / "frontend"
REST_CODES = {value for name, value in vars(ErrorCode).items() if name.isupper()}

needs_frontend = pytest.mark.skipif(
    not (FRONTEND / "src").is_dir(), reason="frontend repo not cloned next to backend"
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


def _section(path: Path, heading: str) -> str:
    """Text under `heading` up to the next heading of the same or a higher level."""
    text = _read(path)
    start = text.index(f"\n{heading}\n")
    level = heading.split(" ")[0]
    end = re.compile(rf"\n#{{1,{len(level)}}} ").search(text, start + len(heading) + 2)
    return text[start : end.start() if end else len(text)]


def _row_codes(text: str) -> list[str]:
    return re.findall(r"^\| `([A-Z_]+)` \|", text, re.MULTILINE)


def _without_code_blocks(text: str) -> str:
    return re.sub(r"```.*?```", "", text, flags=re.DOTALL)


def _markdown_files() -> list[Path]:
    files = [*BACKEND.glob("*.md"), *DOCS.rglob("*.md")]
    if FRONTEND.is_dir():
        files += [*FRONTEND.glob("*.md"), *(FRONTEND / "docs").rglob("*.md")]
    return files


def _test_names() -> set[str]:
    names = set()
    for path in (BACKEND / "tests").glob("test_*.py"):
        for node in ast.walk(ast.parse(_read(path))):
            if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
                names.add(f"{path.stem}::{node.name}")
    return names


# --- API reference (BE) ---------------------------------------------------------------


def test_openapi_snapshot_matches_the_code():
    assert json.loads(_read(DOCS / "openapi.json")) == app.openapi(), (
        "docs/openapi.json is stale: run python -m scripts.export_openapi"
    )


def test_every_setting_is_in_env_example_and_setup_guide():
    example = _read(BACKEND / ".env.example")
    guide = _section(DOCS / "setup_guide.md", "### Backend (`backend/.env`)")
    for name in Settings.model_fields:
        assert re.search(rf"^{name}=", example, re.MULTILINE), f"{name} missing from .env.example"
        assert f"| `{name}` |" in guide, f"{name} missing from setup_guide.md"


def test_documented_scripts_exist():
    for path in _markdown_files():
        for module in re.findall(r"python -m (scripts\.\w+)", _read(path)):
            assert (BACKEND / f"{module.replace('.', '/')}.py").is_file(), f"{path.name}: {module}"


def test_relative_links_resolve():
    for path in _markdown_files():
        for target in re.findall(r"\]\(([^)#\s]+)(?:#[^)]*)?\)", _without_code_blocks(_read(path))):
            if target.startswith(("http://", "https://", "mailto:")):
                continue
            assert (path.parent / target).exists(), f"{path.relative_to(BACKEND.parent)} -> {target}"


# --- Error docs (QA) ------------------------------------------------------------------


def test_error_catalogue_lists_exactly_the_rest_error_codes():
    assert set(_row_codes(_section(DOCS / "error_catalogue.md", "## Codes"))) == REST_CODES


def test_websocket_contract_lists_every_event_and_error_code():
    contract = DOCS / "websocket_contract.md"
    assert set(_row_codes(_section(contract, "### Error codes"))) == set(WS_ERROR_CODES)
    events = _section(contract, "## Event types")
    for event in EventType:
        assert f"`{event.value}`" in events, event.value


def test_error_crosscheck_covers_every_code_with_existing_passing_tests():
    crosscheck = DOCS / "qa" / "error_crosscheck.md"
    existing = _test_names()
    for heading, codes in (("## REST errors", REST_CODES), ("## WebSocket errors", set(WS_ERROR_CODES))):
        section = _section(crosscheck, heading)
        assert set(_row_codes(section)) == codes, heading
        for row in re.findall(r"^\| `[A-Z_]+` \|.*$", section, re.MULTILINE):
            refs = re.findall(r"`(test_\w+::test_\w+)`", row)
            assert refs, f"no test named for {row[:40]}"
            assert row.rstrip().endswith("| Pass |"), row[:40]
    for ref in re.findall(r"`(test_\w+::test_\w+)`", _read(crosscheck)):
        assert ref in existing, f"error_crosscheck.md names a test that does not exist: {ref}"


@needs_frontend
def test_every_websocket_error_code_has_a_frontend_message():
    events_js = _read(FRONTEND / "src" / "realtime" / "events.js")
    block = re.search(r"ROOM_ERROR_MESSAGES = Object\.freeze\(\{(.*?)\}\)", events_js, re.DOTALL)
    assert set(WS_ERROR_CODES) <= set(re.findall(r"^\s*([A-Z_]+):", block.group(1), re.MULTILINE))


# --- UI guide (FE) --------------------------------------------------------------------


@needs_frontend
def test_every_frontend_route_is_in_the_ui_guide():
    routes = _section(FRONTEND / "docs" / "ui_guide.md", "### Screen and route list")
    paths = ["/"] + re.findall(r'path="([^"]+)"', _read(FRONTEND / "src" / "App.jsx"))
    for path in paths:
        if path == "*":
            assert "| anything else |" in routes
            continue
        path = "/" + path.lstrip("/")
        assert re.search(rf"^\| `{re.escape(path)}(\?[^`]*)?` \|", routes, re.MULTILINE), path


@needs_frontend
def test_every_frontend_api_function_is_in_the_ui_guide():
    guide = _section(FRONTEND / "docs" / "ui_guide.md", "### REST (axios)")
    for module in (FRONTEND / "src" / "api").glob("*.js"):
        if module.name.endswith(".test.js") or module.name in ("client.js", "useApiQuery.js"):
            continue
        for name in re.findall(r"^export const (\w+)", _read(module), re.MULTILINE):
            assert f"`{name}`" in guide, f"{module.name}: {name}"

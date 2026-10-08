"""Phase 7 documentation pack and Phase 8 QA records: the docs must stay true to the code.

Fails when an error code, event, setting, route, script, test name or link in the docs no longer
matches the code, or when the defect log or UAT pack shows anything open or unproven. Frontend
checks need the frontend repo cloned next to this one (skipped otherwise).
"""

import ast
import functools
import json
import re
from pathlib import Path

import pytest

from app.core.config import Settings
from app.core.errors import ErrorCode
from app.main import app
from app.realtime.events import WS_ERROR_CODES, EventType
from scripts.package_release import forbidden

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


@functools.cache
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


# --- Phase 8 QA records ---------------------------------------------------------------

TEST_REF = r"`(test_\w+::test_\w+)`"


def _table_rows(text: str, first_cell: str) -> list[list[str]]:
    rows = re.findall(rf"^\| {first_cell} \|.*\|$", text, re.MULTILINE)
    return [[cell.strip() for cell in row.strip("|").split(" | ")] for row in rows]


def _evidence_exists(evidence: str) -> list[str]:
    """Each piece of evidence named in `evidence` that exists (tests, scripts, screenshots, FE tests)."""
    found = [ref for ref in re.findall(TEST_REF, evidence) if ref in _test_names()]
    found += [m for m in re.findall(r"python -m (scripts\.\w+)", evidence) if (BACKEND / f"{m.replace('.', '/')}.py").is_file()]
    found += [p for p in re.findall(r"`(docs/qa/ux/[\w-]+\.jpg)`", evidence) if (BACKEND / p).is_file()]
    if FRONTEND.is_dir():
        found += [f for f in re.findall(r"`(\w+\.test\.jsx?)`", evidence) if any((FRONTEND / "src").rglob(f))]
    return found


def test_qa_docs_name_only_existing_tests():
    existing = _test_names()
    for path in [*(DOCS / "qa").glob("*.md"), DOCS / "handover.md"]:
        for ref in re.findall(TEST_REF, _read(path)):
            assert ref in existing, f"{path.name} names a test that does not exist: {ref}"


def test_defect_log_has_nothing_open_and_every_fix_has_evidence():
    log = _read(DOCS / "qa" / "defect_log.md")
    defects = _table_rows(log, r"D-\d+")
    assert defects, "no defects parsed"
    assert len({row[0] for row in defects}) == len(defects), "duplicate defect ID"
    for row in defects:
        assert row[-1] == "Closed", f"{row[0]} is {row[-1]}"
        assert _evidence_exists(row[-2]), f"{row[0]}: evidence names nothing that exists: {row[-2]}"

    per_severity = [sum(row[1] == f"Sev-{n}" for row in defects) for n in range(1, 5)]
    for label, expected in (("Found", per_severity), ("Closed", per_severity), (r"\*\*Open\*\*", [0] * 4)):
        (cells,) = _table_rows(log, label)
        counts = [int(c.strip("*")) for c in cells[1:]]
        assert counts == [*expected, sum(expected)], f"status row {label}: {counts}"


def test_uat_pack_passes_every_section_6_criterion_with_evidence():
    criteria = _table_rows(_read(DOCS / "qa" / "uat_evidence_pack.md"), r"C-\d\d")
    assert [row[0] for row in criteria] == [f"C-{n:02}" for n in range(1, 12)]
    for row in criteria:
        assert row[-1] == "Pass", f"{row[0]} is {row[-1]}"
        assert re.findall(TEST_REF, row[3]), f"{row[0]} names no automated test"


@pytest.mark.parametrize(
    "name",
    [".env", "app/.env.production", "venv/Lib/site.py", ".venv/x", "app/__pycache__/main.cpython-313.pyc",
     "node_modules/react/index.js", "media/audio/a.wav", "backups/db.dump", "dist/index.html", "app/x.pyc"],
)
def test_release_package_refuses_secrets_environments_and_build_output(name):
    assert forbidden(name)


def test_release_package_keeps_source_and_the_env_example():
    for name in (".env.example", "app/main.py", "src/App.jsx", "docs/qa/ux/home-phone.jpg", "package-lock.json"):
        assert forbidden(name) is None, name

# Documentation Pack & Checklist (ALL)

The complete SoundSync documentation and the Phase 7 checklist. Every item links to its document and says how it was checked. Paths are relative to the two repositories cloned side by side (`backend/`, `frontend/`).

## Where to start

| I want to… | Read |
| --- | --- |
| Build and run everything on a new machine | [`setup_guide.md`](setup_guide.md) |
| Use the app (screens, rooms, admin) | [`../../frontend/docs/ui_guide.md`](../../frontend/docs/ui_guide.md) Part 1 |
| Work on the frontend | [`../../frontend/README.md`](../../frontend/README.md), [`ui_guide.md`](../../frontend/docs/ui_guide.md) Part 2 |
| Work on the API | [`../README.md`](../README.md), OpenAPI at `/docs`, [`error_catalogue.md`](error_catalogue.md) |
| Write a room client / change room sync | [`websocket_contract.md`](websocket_contract.md), [`sync_tuning.md`](sync_tuning.md) |
| Set up, back up or restore the database | [`db_runbook.md`](db_runbook.md), [`schema.md`](schema.md) |
| Test or accept a release | [`qa/acceptance_matrix.md`](qa/acceptance_matrix.md), [`qa/error_crosscheck.md`](qa/error_crosscheck.md) |

## Document index

| Document | Owner | Covers |
| --- | --- | --- |
| [`setup_guide.md`](setup_guide.md) | BE | Clean-machine build and run, every setting, server deployment notes, API reference, troubleshooting |
| [`openapi.json`](openapi.json) (live: `/docs`) | BE | REST API: every endpoint, request, response and error shape |
| [`error_catalogue.md`](error_catalogue.md) | BE | Error codes, HTTP statuses, example requests per area, logging rule |
| [`websocket_contract.md`](websocket_contract.md) | RT | Room WebSocket: connection, close codes, messages, clock sync, timeline, drift rules, error codes, ordering guarantees, how to implement a client |
| [`sync_tuning.md`](sync_tuning.md) | RT | Sync targets, network profiles, measured results, tuning decisions, performance budgets |
| [`schema.md`](schema.md) | DATA | Tables, constraints, indexes, migrations, query rules, performance notes |
| [`db_runbook.md`](db_runbook.md) | DATA | Create, migrate, seed, check, reset, backup, restore; seed fixtures and expected results |
| [`../../frontend/docs/ui_guide.md`](../../frontend/docs/ui_guide.md) | FE | Screen/route list and how to use each screen; how the frontend uses REST and the WebSocket |
| [`../../frontend/README.md`](../../frontend/README.md) | FE | Frontend commands, settings, structure, tests |
| [`../README.md`](../README.md) | BE | Backend overview, contracts, tests and scripts |
| [`qa/error_crosscheck.md`](qa/error_crosscheck.md) | QA | Every error: documented, tested, handled in the UI |
| [`qa/acceptance_matrix.md`](qa/acceptance_matrix.md) | QA | Acceptance cases and results for every phase |

## Phase 7 checklist

| # | Handbook item | Deliverable | Done when (handbook) | Evidence | Status |
| --- | --- | --- | --- | --- | --- |
| 1 | BE: Build + config + API reference | Build steps, env guide, finalized OpenAPI | Clean machine can build/run from docs | `setup_guide.md` sections 1–8. Clean-copy run: the tracked source only (no venv, `node_modules`, media or caches), a new virtualenv and `npm ci`, following the guide, gave all tests passing and a production build (see "Verification run"). `test_openapi_snapshot_matches_the_code` and `test_every_setting_is_in_env_example_and_setup_guide` | Done |
| 2 | RT: WebSocket event/message reference | Message types, payloads, ordering guarantees | New engineer can implement an FE client from docs alone | `websocket_contract.md` v1.3: every event and error code (`test_websocket_contract_lists_every_event_and_error_code`), 11 ordering guarantees enforced by a per-room lock (`test_joiner_mid_burst_sees_events_in_commit_order_with_no_gap`), "Implementing a client" steps and a minimal client | Done |
| 3 | DATA: DB runbook + backup/restore notes | Init/migrate/seed/restore instructions | QA can recreate fixtures from docs | `db_runbook.md`. `python -m scripts.check_db` verifies a database against the seed fixtures (`tests/test_check_db.py`), and the expected results were checked against the live API. `python -m scripts.restore_check` did a full backup and restore onto a fresh PostgreSQL 18 server set up with `setup_db.sql`, into an empty database and again with `--clean`: every table, row, index, constraint, sequence and media file was identical, and `pytest` passed 220 tests on the restored copy. The reset path was also verified (runbook section 8) | Done |
| 4 | FE: Operator/user UI guide | Screen/route list; how FE consumes REST + WebSocket | New engineer can run FE against BE/RT from docs only | `frontend/docs/ui_guide.md`; every route in `App.jsx` and every API function is listed (`test_every_frontend_route_is_in_the_ui_guide`, `test_every_frontend_api_function_is_in_the_ui_guide`) | Done |
| 5 | QA: Error-handling documentation cross-check | Error cases verified and noted | Error suite documented and passing | `qa/error_crosscheck.md`: 17 REST + 7 WebSocket codes, each documented, tested and handled in the UI. Four missing tests added, two dead codes removed, one close-code bug fixed (`test_error_crosscheck_covers_every_code_with_existing_passing_tests`) | Done |
| 6 | ALL: Documentation pack | API, room-sync behaviour, error docs | Documentation checklist satisfied | This page; all relative links resolve and every `python -m scripts.…` command exists (`test_relative_links_resolve`, `test_documented_scripts_exist`) | Done |
| 7 | Packaging: source package | Only source in git | — | Backend repo no longer tracks `venv/`, `.venv/` or `__pycache__` (16,000+ files untracked); `backups/` git-ignored; `.env` never tracked | Done |

## Verification run (2026-10-07)

Clean-copy check of "a clean machine can build and run from the docs":

1. **Clean copy.** Only the files git would ship were copied into an empty folder: 99 backend and 80 frontend files, with no virtualenv, `node_modules`, media, caches or build output. The only extra file was a `.env` pointing at the existing PostgreSQL 18 database (section 1 of the runbook already done).
2. **Backend**, following [`setup_guide.md`](setup_guide.md) section 3:
   - `python -m venv venv` and `pip install -r requirements.txt` succeeded.
   - `alembic current` showed `0005 (head)`.
   - `python -m scripts.seed` regenerated all media.
   - `python -m scripts.check_db` printed 7 × OK.
   - `pytest` passed 220 tests.
   - `fastapi run app/main.py` answered `/health`, `/ready` and `/docs` with 200.
3. **Frontend**, following section 4: `npm ci`, then `npm test` (186 passed), `npm run lint` and `npm run build` all succeeded.
4. The copy (including its `.env`) was deleted afterwards.

## Keeping the pack true

- `tests/test_docs.py` runs with the normal `pytest`, so stale docs fail CI like a broken feature.
- Changed an endpoint? Run `python -m scripts.export_openapi` and update `error_catalogue.md`.
- Changed a room message or rule? Bump `websocket_contract.md` (changelog + sign-off) and notify FE.
- New migration? Update `schema.md`; new setting? Add it to `.env.example` and `setup_guide.md`.
- New screen or API function? Add it to `ui_guide.md`.

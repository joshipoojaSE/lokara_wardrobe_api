# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

FastAPI wardrobe API. Python 3.12, async SQLAlchemy 2.0 + asyncpg (PostgreSQL), Alembic, pydantic-settings.

The project is a deliberate **vertical slice**: one resource (`WardrobeItem`) implemented through every
layer. New features are meant to be copies of that pattern, not new designs. Not a git repository yet.

## Change Policy

Before making changes:

1. Identify the files directly related to the requested feature.
2. Inspect those files and their dependencies.
3. Explain which files need to change.
4. Do not modify unrelated files.
5. Do not perform broad refactoring unless explicitly requested.
6. Reuse existing utilities/services/repositories when possible.
7. Do not create a new abstraction if an existing one can be reused.
8. Do not rename files or functions unless required.
9. Do not change database schema unless explicitly required.
10. Do not change API response formats without explicit approval.

After implementation:

1. List modified files.
2. Explain why each file was changed.
3. List any new files.
4. Mention any migrations required.
5. Mention tests that were added/changed.
6. Mention anything that was intentionally NOT changed.

## Commands

The venv lives at `.venv/`. On Windows, invoke it directly rather than activating:
`.venv/Scripts/python.exe -m <module>`.

```bash
docker compose up -d                 # Postgres only — the usual local setup
docker compose --profile api up -d   # Postgres + API in its production image

.venv/Scripts/python.exe -m uvicorn app.main:app --reload    # serve from the venv
.venv/Scripts/python.exe -m alembic revision --autogenerate -m "msg"
.venv/Scripts/python.exe -m alembic upgrade head
.venv/Scripts/python.exe -m pytest
.venv/Scripts/python.exe -m pytest "tests/test_items.py::test_item_crud_round_trip"
```

There is no linter or formatter configured. `pyproject.toml` holds pytest config only.

## Architecture

### Layering — the rule the codebase exists to demonstrate

Each layer talks only to the one below it:

| Layer | Location | Must not touch |
|---|---|---|
| Route | `app/api/v1/routes/` | ORM models, `AsyncSession` |
| Service | `app/services/` | HTTP, `HTTPException`, FastAPI |
| Repository | `app/repositories/` | schemas, HTTP |
| Model | `app/models/` | everything above |

Routes receive a service via `ItemServiceDep` (`app/api/deps.py`), which composes
`ItemService(ItemRepository(session))`. Adding a resource means adding one file per layer plus a
`Depends` alias in `deps.py` and an `include_router` line in `app/api/v1/router.py`.

### Transactions — one boundary, in one place

`get_session()` in `app/db/session.py` is the **only** thing that commits: it commits on clean exit and
rolls back on exception. Repositories call `flush()`/`refresh()` and never `commit()`. Preserve this —
committing inside a repository breaks the request-level atomicity every route relies on.

### Errors — domain exceptions, translated at the edge

Services raise `NotFoundError` / `ConflictError` from `app/core/exceptions.py`; they never raise
`HTTPException`. Handlers registered by `register_exception_handlers()` translate those to HTTP, so
services stay usable from a CLI or worker. All errors share one envelope, including validation failures:

```json
{"error": {"code": "not_found", "message": "..."}}
```

Tests assert on `response.json()["error"]["code"]`, so changing that shape breaks them.

### Configuration — `DATABASE_URL` is the only environment switch

No code branches on environment. `settings.environment` is declared but unused; `settings.debug` only
sets a log level. Local and production run identical code with a different `DATABASE_URL`.

**The hostname differs by run context and this trips people up:**

- From the venv, Postgres is a published port → `@localhost:5432` (what `.env` holds)
- From inside the `api` container, `localhost` is the container itself → `@db:5432`

`docker-compose.yml` therefore overrides `DATABASE_URL` for the `api` service, listing `environment:`
after `env_file:` so the override wins. Production sets `DATABASE_URL` to a managed instance and runs
no `db` container at all.

## Gotchas

**pytest-asyncio loop scope is load-bearing.** `pyproject.toml` sets *both*
`asyncio_default_fixture_loop_scope` and `asyncio_default_test_loop_scope` to `"session"`. The
session-scoped `engine` fixture holds an asyncpg pool bound to the loop that created it; if tests run on
their own loop, every DB test dies with `got Future attached to a different loop`. This requires
pytest-asyncio ≥ 1.0 — the test-scope option does not exist in 0.25.

**Tests need a separate `_test` database.** `tests/conftest.py` reads `TEST_DATABASE_URL` and does
`drop_all`/`create_all` against it — pointing it at the dev database would wipe it. The compose init
script `scripts/create_test_db.sh` creates `${POSTGRES_DB}_test` on first volume creation only; if the
`pgdata` volume already exists, the script does not re-run.

Test isolation comes from an outer transaction rolled back after each test, not from truncation. The
`client` fixture overrides `get_session` to hand back that same session.

**Use `sa.Uuid`, not `postgresql.UUID`.** `app/db/base.py` uses the dialect-agnostic type. It still
renders a native `uuid` column on Postgres but keeps models portable to SQLite. Note that SQLite tolerates
event-loop mistakes asyncpg rejects, so **verify against Postgres** — a green SQLite run proves less.

**Mixin column order** is controlled by `sort_order` in `app/db/base.py` (`id` at `-100`, timestamps at
`100`). Without it, mixin columns land after the model's own columns in generated DDL.

**`docker compose down -v` destroys `pgdata`**, taking applied migrations with it. Plain `down` is safe.
If a container fails with `network ... not found`, it holds a stale network ID — recreate it with
`docker compose --profile api up -d --force-recreate api`.

## Migrations

`alembic/env.py` is async and pulls the URL from `settings.database_url`, ignoring `sqlalchemy.url` in
`alembic.ini`. It does `from app.models import *` so autogenerate sees the tables — **a new model must be
exported from `app/models/__init__.py` or Alembic will silently miss it.**

Generate migrations against Postgres, never SQLite; the flavor leaks into the file (`now()` vs
`CURRENT_TIMESTAMP`).

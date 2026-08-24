# Architecture

Async FastAPI service over PostgreSQL. This document covers the shape of the system and the
reasoning behind it. For day-to-day commands and pitfalls, see [CLAUDE.md](CLAUDE.md).

## Scope

A single resource — `WardrobeItem` — implemented through every layer, end to end. The point is not
the resource; it is that the path from HTTP request to SQL is fully worked out once, so subsequent
features are copies rather than fresh designs.

Deliberately absent: authentication, caching, background workers, rate limiting, multi-tenancy.
Each of those would impose structure on the layers below, and guessing wrong is more expensive than
adding them when their requirements are real.

## Deployment topology

The same image and the same code run in every context. `DATABASE_URL` is the only thing that varies.

```
                    SAME CODE
                       │
          ┌────────────┴────────────┐
          │                         │
       LOCAL                    PRODUCTION
          │                         │
  DATABASE_URL                DATABASE_URL
          │                         │
          ▼                         ▼
  Docker PostgreSQL          Managed PostgreSQL
```

Three concrete run shapes:

| Context | Process | Reaches Postgres via |
|---|---|---|
| Local, venv | `uvicorn` on the host | `@localhost:5432` (published port) |
| Local, container | `api` service | `@db:5432` (Docker DNS) |
| Production | deployed image | managed instance hostname |

`docker-compose.yml` exists only for local development; the `api` service sits behind a profile, and
no `db` container exists in production. Because the hostname differs between the venv and the
container, compose overrides `DATABASE_URL` for the `api` service, ordering `environment:` after
`env_file:` so the override wins.

No code branches on environment. `settings.environment` is declared but never read; `settings.debug`
only selects a log level. This is the property that makes the diagram true rather than aspirational,
and it is worth defending — the moment a code path asks "am I in production?", local runs stop
proving anything about production.

## Layers

```
HTTP ─▶ Route ─▶ Service ─▶ Repository ─▶ Model ─▶ PostgreSQL
        schemas   domain      SQLAlchemy   table
                  errors      queries
```

Each layer talks only to the one below it. The constraint is what gives the structure value:

| Layer | Directory | Responsibility | Must not touch |
|---|---|---|---|
| Route | `app/api/v1/routes/` | HTTP shape, status codes, query params | ORM models, `AsyncSession` |
| Service | `app/services/` | business rules, domain errors | HTTP, `HTTPException`, FastAPI |
| Repository | `app/repositories/` | queries, persistence | Pydantic schemas, HTTP |
| Model | `app/models/` | table definition | everything above |

Wiring happens in `app/api/deps.py`, which is the only place the layers are assembled:

```python
DbSession      = Annotated[AsyncSession, Depends(get_session)]
ItemServiceDep = Annotated[ItemService, Depends(get_item_service)]   # ItemService(ItemRepository(session))
```

Routes declare `service: ItemServiceDep` and never see a session. Adding a resource means one file
per layer, one alias in `deps.py`, one `include_router` line in `app/api/v1/router.py`.

## Request lifecycle

Tracing `PATCH /api/v1/items/{id}`, because it touches every mechanism at once:

1. **FastAPI** validates the path `UUID` and parses the body into `ItemUpdate`. A failure here never
   reaches application code — the `RequestValidationError` handler returns 422 in the standard envelope.
2. **`get_session`** opens an `AsyncSession` and yields it. This is the transaction boundary.
3. **`get_item_service`** composes `ItemService(ItemRepository(session))`.
4. **Route** calls `service.update_item(item_id, payload)`.
5. **Service** loads the item, raising `NotFoundError` if absent, then applies
   `payload.model_dump(exclude_unset=True)` — only fields the client actually sent, which is what makes
   this a true PATCH rather than a disguised PUT.
6. **Repository** sets the attributes, `flush()`es to emit the UPDATE, and `refresh()`es to read back
   server-generated values (`updated_at` comes from `now()`, not from Python).
7. **FastAPI** serializes the returned ORM object through `response_model=ItemRead`.
8. **`get_session`** commits during dependency teardown.

Errors short-circuit this: `NotFoundError` propagates untouched through the route, the
`AppError` handler maps `exc.status_code`/`exc.code` onto the response, and `get_session` rolls back.

## Key design decisions

### One transaction boundary, owned by the session dependency

`get_session` in `app/db/session.py` is the only code that commits. Repositories call `flush()` and
never `commit()`.

A route is therefore atomic by construction: a service can call three repositories, and a failure in
the third rolls back the first two with no coordinating code. Distributing commits into repositories
is the single change most likely to break this, and it degrades silently — each operation still
appears to work.

**Ordering worth knowing.** FastAPI runs `yield`-dependency teardown after the response has been
serialized, so the real sequence is:

```
route returns  ─▶  response_model serialization  ─▶  commit
```

The response body is therefore built from flushed-but-uncommitted state. That is safe here — the
repository's `flush()` + `refresh()` has already read back server-generated values, so nothing is
missing — and a commit that fails at teardown still surfaces to the client as a failure rather than a
false success.

The caveat is *which* failure. By that point the exception handlers have already run, so a commit
error escapes as a bare `500 Internal Server Error`, bypassing the `{"error": {...}}` envelope every
other failure uses. Operations that need a commit failure reported in the standard shape should commit
explicitly inside the service, where `AppError` handling still applies; the dependency's commit then
becomes a no-op.

### Domain errors, translated only at the edge

Services raise `NotFoundError` / `ConflictError` (`app/core/exceptions.py`), never `HTTPException`.
`register_exception_handlers` translates them, reading `status_code` and `code` off the exception class.

This keeps services callable from a CLI, a worker, or a test with no HTTP machinery, and it puts the
response format in one place. Every error — domain and validation alike — shares one envelope:

```json
{"error": {"code": "not_found", "message": "..."}}
```

Adding an error type means one subclass with two class attributes; no handler changes.

### `expire_on_commit=False`

Set on the session factory. After a commit, SQLAlchemy would ordinarily expire loaded instances so the
next attribute access re-fetches — which in async code raises rather than lazily loading. Disabling
expiry lets ORM objects be returned from services and serialized safely. Combined with the
`flush()` + `refresh()` pattern, response data is fully populated before it leaves the repository.

`autoflush=False` is set for the same reason in reverse: flushes happen where the code says they do,
so the emitted SQL is predictable.

### `sa.Uuid`, not `postgresql.UUID`

`app/db/base.py` uses the dialect-agnostic type. It still renders a native `uuid` column on
PostgreSQL, but models remain loadable under SQLite. Keys are generated in Python (`uuid4`) rather
than by the database, so an object has its identity before it is ever flushed.

Note the asymmetry this creates in testing: SQLite tolerates event-loop errors that asyncpg rejects,
so a green SQLite run proves strictly less than a green Postgres run. Verify against Postgres.

### Schema owned by Alembic, never by the application

`create_app()` does not call `create_all`. The lifespan handler configures logging and disposes the
engine; nothing else. Schema changes arrive only through migrations, so local and production converge
by the same mechanism.

`alembic/env.py` is async and reads the URL from `settings.database_url`, ignoring `sqlalchemy.url` in
`alembic.ini` — one source of truth. It does `from app.models import *`, which is why a new model must
be exported from `app/models/__init__.py`; otherwise autogenerate silently emits an empty migration.

### App factory

`create_app()` builds the application; `app = create_app()` at module scope is what uvicorn imports.
Tests call the factory directly to get an isolated instance with its own `dependency_overrides`.

The engine, by contrast, is module-level and process-global. `create_async_engine` opens no
connection at import time, so this is safe, and it means repeated `create_app()` calls share one pool.
Tests never rely on that pool — they override `get_session` entirely.

## Data model

`WardrobeItem` composes two mixins from `app/db/base.py`: `UUIDMixin` (uuid4 primary key) and
`TimestampMixin` (`created_at`, `updated_at`, both `timestamptz`, defaulted and updated by the
database via `now()`).

`sort_order` on the mixin columns (`-100` for `id`, `100` for timestamps) controls position in
generated DDL — without it, inherited columns land after the model's own, and every migration reads
oddly. Indexes exist on the two fields the API filters and sorts by: `name` and `category`.

## Testing architecture

`tests/conftest.py` builds three layered fixtures:

- **`engine`** (session-scoped) — points at `TEST_DATABASE_URL`, `drop_all` + `create_all` around the
  whole run. A separate database, because it is dropped.
- **`session`** (function-scoped) — opens a connection, begins an outer transaction, binds a session to
  it, and rolls back afterward. Isolation comes from rollback, not truncation, which is why tests are
  fast and order-independent.
- **`client`** — an `AsyncClient` over `ASGITransport`, with `get_session` overridden to yield that same
  session. No network, no running server; the app is exercised in-process while sharing the test's
  transaction.

Because the client and the test share one session, a test can assert over HTTP and inspect the
database in the same transaction.

**Event loop scoping is load-bearing.** `pyproject.toml` sets both `asyncio_default_fixture_loop_scope`
and `asyncio_default_test_loop_scope` to `"session"`. The session-scoped engine holds an asyncpg pool
bound to the loop that created it; if tests run on their own loop, every database test fails with
`got Future attached to a different loop`. This requires pytest-asyncio ≥ 1.0.

## Known limitations

- **List endpoints return a bare array.** No total count or pagination envelope. Deferred rather than
  guessed at, since the shape depends on what clients need.
- **`ItemService` is nearly a pass-through.** That is intentional — it is the seam where rules will
  land. It should not be collapsed into the route.
- **No authentication**, so no ownership model. Adding users will mean scoping queries by owner at the
  repository level, which is why repositories take their filters as arguments rather than reading
  ambient state.
- **CORS defaults to `*`.** Correct for local development, wrong for production; set `CORS_ORIGINS`.
- **`poolclass=None` in `alembic/env.py`** is a no-op (SQLAlchemy reads `None` as "use the default").
  Harmless, but `NullPool` is what one-shot migration runs normally want.

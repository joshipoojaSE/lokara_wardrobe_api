# lokara_wardrobe

Async REST API for managing a wardrobe. FastAPI, PostgreSQL, SQLAlchemy 2.0.

Built as a **vertical slice**: one resource implemented cleanly through every layer — route, service,
repository, model — so new features are copies of a working pattern rather than fresh designs.

## Requirements

- Python 3.12
- Docker (local PostgreSQL only; production uses a managed database)

## Setup

```bash
# 1. dependencies
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt     # Windows
# source .venv/bin/activate && pip install -r requirements.txt  # macOS / Linux

# 2. configuration
cp .env.example .env
# then fill in S3_BUCKET / S3_REGION / AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY:
# item creation uploads images and fails without a reachable bucket.

# 3. start PostgreSQL
docker compose up -d

# 4. create the schema
.venv/Scripts/python.exe -m alembic upgrade head

# 5. run
.venv/Scripts/python.exe -m uvicorn app.main:app --reload
```

Then open **http://localhost:8000/docs**.

Examples below use `.venv/Scripts/python.exe -m <tool>` (Windows). With the venv activated, or on
macOS/Linux, `alembic`, `pytest`, and `uvicorn` work directly.

### Running the API in Docker instead

The `api` service sits behind a compose profile, so it stays out of the way by default:

```bash
docker compose up -d               # Postgres only  (the usual case)
docker compose --profile api up -d # Postgres + API in its production image
```

Running from the venv gives faster reload and a debugger you can attach. Use the profile when you want
dev/prod parity.

## Usage

```bash
# create — multipart/form-data; images only, at least one file required
curl -X POST localhost:8000/api/v1/items \
  -F images=@coat-front.jpg -F images=@coat-back.jpg

# describe it — details are set after creation, never at POST
curl -X PATCH localhost:8000/api/v1/items/{id} -H 'Content-Type: application/json' \
  -d '{"name":"Wool Coat","category":"outerwear","color":"charcoal"}'

# list (newest first; filter and paginate)
curl 'localhost:8000/api/v1/items?category=outerwear&limit=20&offset=0'

# fetch, partial update, delete
curl localhost:8000/api/v1/items/{id}
curl -X PATCH localhost:8000/api/v1/items/{id} -H 'Content-Type: application/json' -d '{"size":"L"}'
curl -X DELETE localhost:8000/api/v1/items/{id}
```

| Method | Path | Success |
|---|---|---|
| GET | `/api/v1/health` | 200 |
| POST | `/api/v1/items` | 201 |
| GET | `/api/v1/items` | 200 |
| GET | `/api/v1/items/{id}` | 200 |
| PATCH | `/api/v1/items/{id}` | 200 |
| DELETE | `/api/v1/items/{id}` | 204 |

Errors share one envelope — `{"error": {"code": "...", "message": "..."}}`. Full parameter and
response documentation is in **[API.md](API.md)**.

## Testing

```bash
.venv/Scripts/python.exe -m pytest
.venv/Scripts/python.exe -m pytest "tests/test_items.py::test_item_crud_round_trip"   # one test
```

Tests need the `lokara_wardrobe_test` database, which `docker compose` creates on first startup. If the
`pgdata` volume already existed when that script was added, create it once by hand:

```bash
docker compose exec db psql -U postgres -c "CREATE DATABASE lokara_wardrobe_test;"
```

Each test runs inside a transaction that is rolled back afterward, so tests are isolated and
order-independent. The suite is dropped and recreated per run — never point `TEST_DATABASE_URL` at
your development database.

## Migrations

```bash
.venv/Scripts/python.exe -m alembic upgrade head                          # apply
.venv/Scripts/python.exe -m alembic revision --autogenerate -m "message"  # generate
.venv/Scripts/python.exe -m alembic check                                 # detect model drift
```

Generate migrations against PostgreSQL, never SQLite — the dialect leaks into the generated file. A
new model must be exported from `app/models/__init__.py`, or autogenerate produces an empty migration
with no error. Details in **[DATABASE.md](DATABASE.md)**.

## Configuration

All settings come from environment variables or `.env` (see `.env.example`).

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | local Postgres | **the only thing that differs between environments** |
| `TEST_DATABASE_URL` | `..._test` | dropped and recreated by the test suite |
| `S3_BUCKET`, `S3_REGION` | `lokara-wardrobe`, `ap-south-1` | where item images are stored |
| `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` | unset | omit to fall back to the ambient AWS credential chain (IAM role, profile) |
| `S3_ENDPOINT_URL` | unset | set for MinIO / LocalStack |
| `S3_PRESIGN_EXPIRY_SECONDS` | `3600` | lifetime of the image URLs in responses |
| `IMAGE_MAX_BYTES`, `IMAGE_MAX_COUNT` | `5242880`, `8` | per-file and per-request upload limits |
| `IMAGE_ALLOWED_CONTENT_TYPES` | jpeg, png, webp | JSON array; anything else is a 422 |
| `API_V1_PREFIX` | `/api/v1` | route prefix |
| `CORS_ORIGINS` | `["*"]` | restrict before deploying |
| `DEBUG` | `false` | log verbosity only |
| `APP_NAME`, `ENVIRONMENT` | | labels; no code branches on them |

No code path branches on environment — local and production run identical code against different
databases:

```
                    SAME CODE
          ┌────────────┴────────────┐
       LOCAL                    PRODUCTION
          ▼                         ▼
 Docker PostgreSQL          Managed PostgreSQL
```

One gotcha: from the venv the database host is `localhost`, but from inside the `api` container it is
`db`. Compose overrides `DATABASE_URL` accordingly.

## Project structure

```
app/
├── main.py              create_app() factory, lifespan, middleware
├── core/                config (pydantic-settings), domain errors, logging
├── db/                  Base + mixins, async engine, get_session()
├── models/              SQLAlchemy ORM models
├── schemas/             Pydantic request/response models
├── repositories/        queries; never commits
├── storage/             S3 object storage behind an ImageStorage Protocol
├── services/            business rules; no HTTP knowledge
└── api/
    ├── deps.py          dependency wiring (the only place layers are assembled)
    └── v1/routes/       HTTP endpoints
alembic/                 migration environment and versions
tests/                   fixtures + endpoint tests
scripts/                 Postgres init (creates the test database)
```

Requests flow strictly downward, each layer knowing only the one below it:

```
HTTP ─▶ Route ─▶ Service ─▶ Repository ─▶ Model ─▶ PostgreSQL
                     └────▶ Storage ────────────▶ S3
```

Two invariants hold this together: `get_session()` is the **only** thing that commits, and services
raise domain errors (`NotFoundError`) that handlers translate to HTTP, never `HTTPException`.

### Adding a resource

One file per layer, mirroring `item.py` in each: model → schema → repository → service → route. Then
export the model from `app/models/__init__.py`, add a dependency alias in `app/api/deps.py`, and
register the router in `app/api/v1/router.py`.

## Documentation

| Document | Contents |
|---|---|
| **[API.md](API.md)** | endpoints, parameters, response shapes, error codes |
| **[ARCHITECTURE.md](ARCHITECTURE.md)** | components, request lifecycle, design decisions |
| **[DATABASE.md](DATABASE.md)** | schema, columns, migration mechanics |
| **[CLAUDE.md](CLAUDE.md)** | guidance for Claude Code |

## Not included

No authentication, caching, background workers, or rate limiting. Each would impose structure on the
layers below, and adding them against real requirements beats guessing. List endpoints return a bare
array with no pagination envelope for the same reason.

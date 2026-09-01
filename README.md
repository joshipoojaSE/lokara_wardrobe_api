# Lokara Wardrobe

**Photograph your clothes, then ask your own closet what to wear.**

An async REST API that describes each garment with a vision model, embeds that description, and
answers natural-language questions — *"what goes with my white shirt, but not the tailored
trousers?"* — with items you actually own.

![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?logo=fastapi&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-pgvector-4169E1?logo=postgresql&logoColor=white)
![SQLAlchemy](https://img.shields.io/badge/SQLAlchemy-2.0%20async-D71F00)
![Tests](https://img.shields.io/badge/tests-42%20passing-brightgreen)

---

## The demo

**1. Add an item — photos only, no typing.**

<img src="docs/images/white-shirt.webp" alt="White fitted button-down shirt" height="150">

```bash
curl -X POST localhost:8000/api/v1/items -F images=@white-shirt.jpg
# {"id":"4c605ffe-...","analysis_status":"pending", ...}
```

The upload returns immediately and a background task runs the vision analysis. It writes a title —
`White Fitted Button-Down Shirt` — plus `color_family`, `material`, `fit`, `neckline`, `occasion`,
`pairing_suggestions` and two dozen more fields. An embedding of that description is what search
matches on.

**2. Ask a question about what you own.**

```bash
curl -G localhost:8000/api/v1/items/search \
  --data-urlencode 'q=i want to wear something with my white shirt but not with Tailored Trousers'
```

**3. Get a written answer, and the items behind it.**

```json
{
  "answer": "You can wear your white fitted button-down shirt with your black wide-leg palazzo pants instead of tailored trousers. The fitted shirt balances the relaxed wide-leg shape, and the white-and-black pairing keeps it clean and office-ready.",
  "has_match": true,
  "items": [
    {
      "item_id": "4c605ffe-1f02-49bd-a7c7-7afc9af3a466",
      "title": "White Fitted Button-Down Shirt",
      "image_url": "https://...s3.amazonaws.com/items/4c605ffe-.../e1515777-....webp?X-Amz-Signature=...",
      "reason": "This is your white shirt and works as the anchor for the outfit."
    },
    {
      "item_id": "77e8b9a9-1542-4e1f-bba7-a30ed9e300e4",
      "title": "Black Wide-Leg Palazzo Pants",
      "image_url": "https://...s3.amazonaws.com/items/77e8b9a9-.../2d8940a9-....webp?X-Amz-Signature=...",
      "reason": "These are not tailored trousers, and their black wide-leg shape pairs well with a fitted button-down shirt."
    }
  ]
}
```

Which a client renders as two cards:

<table>
<tr>
<td align="center" width="50%"><img src="docs/images/white-shirt.webp" alt="White fitted button-down shirt" height="170"></td>
<td align="center" width="50%"><img src="docs/images/palazzo-pants.webp" alt="Black wide-leg palazzo pants" height="170"></td>
</tr>
<tr>
<td align="center"><b>White Fitted Button-Down Shirt</b><br>the anchor for the outfit</td>
<td align="center"><b>Black Wide-Leg Palazzo Pants</b><br>not tailored trousers, and the wide leg balances a fitted shirt</td>
</tr>
</table>

Note that the query excluded the tailored trousers — which the user does own. The answer respects the
exclusion and reaches for a different bottom.

---

## The interesting problems

### A recommendation must not invent a garment you don't own

The obvious design — let the model return item UUIDs — fails quietly: a hallucinated id looks exactly
like a real one until you query for it. So the model never sees an id. Items are described to it by
**1-based position** in the prompt, it cites positions, and the service maps them back, dropping
anything outside the retrieved window ([`_resolve_picks`](app/services/item.py)).

A position is a single token the model cannot plausibly typo into another valid item, and an
out-of-range index is detectable without a database round trip. Which items an answer names is
therefore grounded *by construction*, not by trusting the model. `title` and `image_url` are read off
the retrieved row too — never the model's recollection of it. Only the prose is generated.

### Ranking by similarity gives the wrong window for an outfit

One query vector ranks the whole wardrobe by a single notion of closeness, so `hits[:limit]` for
*"what goes with my white shirt"* fills every slot with **shirts** — and the bottoms the answer needs
never reach the prompt. The model then has nothing to pair with and falls back on suggesting garments
that were never retrieved.

[`select_window`](app/answers/context.py) fills the context round-robin over garment type instead:
closest Top, closest Bottom, closest Footwear, and around again. Groups are visited in order of their
best hit, so the strongest match in the wardrobe still lands at position 1. The cost is honest — an
irrelevant accessory can displace a third relevant top — and it is the trade an outfit question
needs.

### A search result is not a match

Similarity search always returns its closest rows, whether or not they answer the question. So the
response carries **`has_match`**: `false` means the wardrobe does not contain what was asked for and
the reply is offering the nearest thing instead. `items` holds only what the model chose to show —
never the raw ranking — and may be empty, with `answer` explaining why.

### Failures stay contained to the thing that failed

An embedding call that fails stores a null vector rather than aborting item creation; the item exists
and is simply unfindable until backfilled. Analysis runs in the background behind an
`analysis_status` lifecycle (`pending → ready | failed`), so a vision-model outage never blocks an
upload. A retrieval failure short-circuits before the answering model is ever called, rather than
being reported as an empty result.

### One transaction boundary, in one place

[`get_session()`](app/db/session.py) is the **only** thing that commits — on clean exit, rolling back
on exception. Repositories `flush()` and `refresh()` but never `commit()`, so every route is atomic
by default and no repository can half-write a request. The tests get their isolation from the same
property: each runs inside an outer transaction that is rolled back afterward, so the suite is
order-independent without truncating tables.

### Layers that cannot quietly leak into each other

| Layer | Location | Must not touch |
|---|---|---|
| Route | `app/api/v1/routes/` | ORM models, `AsyncSession` |
| Service | `app/services/` | HTTP, `HTTPException`, FastAPI |
| Repository | `app/repositories/` | schemas, HTTP |
| Model | `app/models/` | everything above |

Services raise domain errors (`NotFoundError`, `ConflictError`) that handlers translate at the edge —
never `HTTPException` — so the service layer stays callable from a CLI or a worker. Every error,
validation failures included, shares one envelope: `{"error": {"code": "...", "message": "..."}}`.

---

## Architecture

```
HTTP ─▶ Route ─▶ Service ─▶ Repository ─▶ Model ─▶ PostgreSQL + pgvector
                     ├────▶ Storage ────────────▶ S3
                     ├────▶ Analysis   (vision)
                     ├────▶ Embeddings
                     └────▶ Answers    (grounded generation)
```

A search request costs two model calls: one to embed the query, one to answer. Ranking is cosine
distance computed in Postgres, ordered so the `vector_cosine_ops` index is actually usable — L2 or
inner product would silently miss it.

```
app/
├── main.py              create_app() factory, lifespan, middleware
├── core/                config (pydantic-settings), domain errors, logging
├── db/                  Base + mixins, async engine, get_session()
├── models/              SQLAlchemy ORM models
├── schemas/             Pydantic request/response models
├── repositories/        queries; never commits
├── storage/             S3 behind an ImageStorage Protocol
├── analysis/            vision analysis behind a Protocol
├── embeddings/          embedding client behind a Protocol
├── answers/             prompt building, context window, grounded answering
├── services/            business rules; no HTTP knowledge
└── api/
    ├── deps.py          dependency wiring (the only place layers are assembled)
    └── v1/routes/       HTTP endpoints
```

Each external dependency sits behind a `Protocol`, which is what makes the suite runnable without an
OpenAI key or an S3 bucket.

### Stack

| | |
|---|---|
| **API** | FastAPI, Pydantic v2, uvicorn |
| **Data** | PostgreSQL + pgvector, SQLAlchemy 2.0 (async), asyncpg, Alembic |
| **AI** | OpenAI vision analysis, `text-embedding-3-small` (1536-d), structured-output answering |
| **Storage** | S3, private bucket, presigned reads |
| **Tests** | pytest, pytest-asyncio, httpx — 42 tests against real Postgres |

---

## Endpoints

| Method | Path | Success | |
|---|---|---|---|
| GET | `/api/v1/health` | 200 | |
| POST | `/api/v1/items` | 201 | multipart images; analysis runs in the background |
| GET | `/api/v1/items` | 200 | newest first, filterable, paginated |
| GET | `/api/v1/items/search` | 200 | **natural language in, a written answer out** |
| GET | `/api/v1/items/{id}` | 200 | |
| PATCH | `/api/v1/items/{id}` | 200 | partial update |
| DELETE | `/api/v1/items/{id}` | 204 | |

Full parameters, response shapes and error codes: **[API.md](API.md)**.

---

## Run it

```bash
# 1. dependencies
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt     # Windows
# source .venv/bin/activate && pip install -r requirements.txt  # macOS / Linux

# 2. configuration
cp .env.example .env
# S3_BUCKET / S3_REGION / AWS credentials — item creation uploads images and
# fails without a reachable bucket. OPENAI_API_KEY — without it items are never
# described and search cannot answer.

# 3. Postgres, schema, server
docker compose up -d
.venv/Scripts/python.exe -m alembic upgrade head
.venv/Scripts/python.exe -m uvicorn app.main:app --reload
```

Then open **http://localhost:8000/docs** for the interactive OpenAPI UI.

<details>
<summary><b>Docker, Windows shells, and migrations</b></summary>

<br>

The API itself sits behind a compose profile, so it stays out of the way by default:

```bash
docker compose up -d               # Postgres only (the usual case)
docker compose --profile api up -d # Postgres + API in its production image
```

Running from the venv gives faster reload and a debugger you can attach; use the profile for
dev/prod parity. From the venv the database host is `localhost`, but from inside the `api` container
it is `db`, and compose overrides `DATABASE_URL` accordingly.

**In `cmd.exe`, swap the slashes** — `cmd` reads a leading `/` as an option switch:

```cmd
.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

Migrations:

```bash
.venv/Scripts/python.exe -m alembic upgrade head                          # apply
.venv/Scripts/python.exe -m alembic revision --autogenerate -m "message"  # generate
.venv/Scripts/python.exe -m alembic check                                 # detect model drift
```

Generate against PostgreSQL, never SQLite — the dialect leaks into the generated file. A new model
must be exported from `app/models/__init__.py`, or autogenerate produces an empty migration with no
error. Details in **[DATABASE.md](DATABASE.md)**.

</details>

---

## Tests

```bash
.venv/Scripts/python.exe -m pytest
.venv/Scripts/python.exe -m pytest "tests/test_items.py::test_item_crud_round_trip"   # one test
```

42 tests across CRUD, image validation, analysis, embeddings, search and answering. They run against
a real PostgreSQL instance rather than SQLite — asyncpg rejects event-loop mistakes SQLite tolerates,
so a green SQLite run would prove less. The `lokara_wardrobe_test` database is created by compose on
first startup; the suite is dropped and recreated per run, so never point `TEST_DATABASE_URL` at your
development database.

---

## Configuration

Every setting comes from environment variables or `.env` (see `.env.example`). **No code path
branches on environment** — local and production run identical code against a different
`DATABASE_URL`.

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | local Postgres | the only thing that differs between environments |
| `TEST_DATABASE_URL` | `..._test` | dropped and recreated by the test suite |
| `S3_BUCKET`, `S3_REGION` | `lokara-wardrobe`, `ap-south-1` | where item images are stored |
| `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` | unset | omit to use the ambient AWS credential chain |
| `S3_ENDPOINT_URL` | unset | set for MinIO / LocalStack |
| `S3_PRESIGN_EXPIRY_SECONDS` | `3600` | lifetime of the image URLs in responses |
| `IMAGE_MAX_BYTES`, `IMAGE_MAX_COUNT` | `5242880`, `8` | per-file and per-request upload limits |
| `IMAGE_ALLOWED_CONTENT_TYPES` | jpeg, png, webp | JSON array; anything else is a 422 |
| `OPENAI_API_KEY` | unset | vision, embeddings and answers; omit to use the ambient key |
| `ANSWER_MODEL`, `EMBEDDING_MODEL` | `gpt-5.5`, `text-embedding-3-small` | the models behind `/items/search` |
| `ANSWER_CONTEXT_ITEMS` | `12` | retrieved items the answering model sees |
| `API_V1_PREFIX` | `/api/v1` | route prefix |
| `CORS_ORIGINS` | `["*"]` | restrict before deploying |

---

## Documentation

| Document | Contents |
|---|---|
| **[API.md](API.md)** | endpoints, parameters, response shapes, error codes |
| **[ARCHITECTURE.md](ARCHITECTURE.md)** | components, request lifecycle, design decisions |
| **[DATABASE.md](DATABASE.md)** | schema, columns, migration mechanics |

## Scope

No authentication, caching, background workers, or rate limiting. Each would impose structure on the
layers below, and building them against real requirements beats guessing at them — list endpoints
return a bare array with no pagination envelope for the same reason.

The codebase is a deliberate **vertical slice**: one resource carried cleanly through every layer, so
adding the next one is a copy of a working pattern rather than a fresh design.

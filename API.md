# API Reference

Base path: `/api/v1` (configurable via `API_V1_PREFIX`).

Interactive docs on a running instance: `/docs` (Swagger), `/redoc`, `/api/v1/openapi.json`.

Every response body below was captured from a live instance, not transcribed from the models.

## Conventions

- **Content type** — `application/json` for all requests and responses, except `204`, which has an
  empty body.
- **Timestamps** — ISO 8601, UTC, `Z`-suffixed: `2026-08-24T07:03:11.948765Z`.
- **IDs** — UUID (v4) strings. A malformed UUID in the path is a `422`, never a `404`.
- **Authentication** — none. Every endpoint is public.
- **CORS** — `CORS_ORIGINS` defaults to `*`; credentials allowed, all methods and headers.

### Error envelope

Every error shares one shape:

```json
{"error": {"code": "not_found", "message": "Wardrobe item ... not found."}}
```

`422` adds a `details` array carrying the raw Pydantic errors:

```json
{
  "error": {
    "code": "validation_error",
    "message": "Request validation failed.",
    "details": [
      {"type": "missing", "loc": ["body", "category"], "msg": "Field required", "input": {"name": "x"}}
    ]
  }
}
```

| Status | `code` | Cause |
|---|---|---|
| 404 | `not_found` | no item with that id |
| 409 | `conflict` | defined in `app/core/exceptions.py`, not yet raised anywhere |
| 422 | `validation_error` | body, query, or path validation failed |
| 500 | `internal_error` | unhandled `AppError` |

> **Caveat:** a failure inside the session commit occurs after exception handlers have run, so it
> escapes as a bare `500 Internal Server Error` **without** this envelope. See ARCHITECTURE.md.

## Endpoints

| Method | Path | Success | Notes |
|---|---|---|---|
| GET | `/api/v1/health` | 200 | no DB access |
| POST | `/api/v1/items` | 201 | |
| GET | `/api/v1/items` | 200 | bare array, no envelope |
| GET | `/api/v1/items/{item_id}` | 200 | |
| PATCH | `/api/v1/items/{item_id}` | 200 | partial update |
| DELETE | `/api/v1/items/{item_id}` | 204 | empty body |

---

### `GET /health`

Liveness only — it does **not** touch the database, so a 200 here does not mean Postgres is reachable.
Use `GET /items` for that.

```json
{"status": "ok"}
```

---

### `POST /items`

Request body — `ItemCreate`:

| Field | Type | Required | Constraints |
|---|---|---|---|
| `name` | string | **yes** | 1–120 chars |
| `category` | string | **yes** | 1–50 chars, free text (no enum) |
| `color` | string \| null | no | ≤ 40 chars |
| `brand` | string \| null | no | ≤ 80 chars |
| `size` | string \| null | no | ≤ 20 chars |
| `notes` | string \| null | no | unbounded |

```bash
curl -X POST localhost:8000/api/v1/items -H 'Content-Type: application/json' \
  -d '{"name":"Wool Coat","category":"outerwear","color":"charcoal","brand":"Acme","size":"L","notes":"winter only"}'
```

**201** — the full `ItemRead` object. Omitted optional fields come back explicitly `null`:

```json
{
  "name": "Wool Coat",
  "category": "outerwear",
  "color": "charcoal",
  "brand": "Acme",
  "size": "L",
  "notes": "winter only",
  "id": "152069c4-e4e5-4d54-bd5c-3360b5b39ce2",
  "created_at": "2026-08-24T07:03:11.962456Z",
  "updated_at": "2026-08-24T07:03:11.962456Z"
}
```

`created_at` and `updated_at` are identical on creation.

**422** — missing or invalid fields.

> **Unknown fields are silently ignored.** `{"name":"Y","category":"tops","bogus":1}` returns **201**,
> with `bogus` discarded and no warning. A client that misspells a field gets a success response and a
> silently incomplete record. Set `model_config = ConfigDict(extra="forbid")` on `ItemBase` if you want
> typos rejected.

---

### `GET /items`

| Param | Type | Default | Constraints |
|---|---|---|---|
| `limit` | integer | 50 | 1–200 (outside → 422) |
| `offset` | integer | 0 | ≥ 0 (negative → 422) |
| `category` | string | — | exact match, case-sensitive |

Returns a **bare JSON array**, newest first (`created_at DESC`). There is no wrapper object, no total
count, and no next-page cursor — a client cannot tell a last page from a full one except by receiving
fewer than `limit` results.

```bash
curl 'localhost:8000/api/v1/items?category=tops&limit=1&offset=1'
```

```json
[
  {
    "name": "Linen Shirt", "category": "tops", "color": "white",
    "brand": null, "size": null, "notes": null,
    "id": "d10cdc83-24b2-4375-9901-11bec4ccb510",
    "created_at": "2026-08-24T07:03:11.948765Z",
    "updated_at": "2026-08-24T07:03:11.948765Z"
  }
]
```

An empty result is `[]` with **200**, never 404.

---

### `GET /items/{item_id}`

**200** — an `ItemRead`. **404** if no such item. **422** if `item_id` is not a valid UUID:

```json
{"error": {"code": "validation_error", "message": "Request validation failed.",
 "details": [{"type": "uuid_parsing", "loc": ["path", "item_id"], "msg": "Input should be a valid UUID, ..."}]}}
```

---

### `PATCH /items/{item_id}`

True partial update — only fields present in the body are applied (`exclude_unset=True`). Every field
of `ItemCreate` is optional here, with the same length constraints; `name` and `category` remain
non-empty when supplied.

```bash
curl -X PATCH localhost:8000/api/v1/items/{id} -H 'Content-Type: application/json' -d '{"size":"M"}'
```

**200** — the complete updated object. Three behaviors confirmed against a live instance:

| Body | Effect |
|---|---|
| `{"size": "M"}` | sets `size`; all other fields untouched; `updated_at` advances |
| `{"color": null}` | **clears** `color` — explicit `null` counts as "set" |
| `{}` | 200, no change, **`updated_at` does not advance** (no UPDATE is emitted) |

The distinction in row two is the useful one: omitting a field leaves it alone, while sending `null`
erases it. There is no way to distinguish "clear this" from "ignore this" other than presence.

**404** if the item does not exist — the lookup happens before any mutation.

---

### `DELETE /items/{item_id}`

**204** with an empty body on success. **404** if the item does not exist (deletes are not idempotent
in the "always 204" sense — a second delete returns 404). Hard delete; there is no soft-delete flag.

## Response object — `ItemRead`

```
name, category, color, brand, size, notes, id, created_at, updated_at
```

Serialization order follows the schema's inheritance (`ItemBase` fields first, then `id` and the
timestamps). Nullable fields are always present and explicitly `null` — never omitted.

## Known gaps

- **404 is absent from the OpenAPI schema.** The spec advertises only `200`/`201`/`422` per operation,
  because `NotFoundError` is translated by an app-level handler rather than declared on the routes.
  `/docs` therefore understates the real contract, and generated clients will not model 404. Fixing it
  means adding `responses={404: ...}` to the affected route decorators.
- **No pagination metadata**, as above.
- **`category` is unvalidated free text.** `"tops"` and `"Tops"` are different categories, and filtering
  is exact-match.
- **No sorting or search parameters** — order is fixed at `created_at DESC`.
- **`409 conflict` is defined but unreachable**; nothing raises `ConflictError` yet.

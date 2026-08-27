# API Reference

Base path: `/api/v1` (configurable via `API_V1_PREFIX`).

Interactive docs on a running instance: `/docs` (Swagger), `/redoc`, `/api/v1/openapi.json`.

Every response body below was captured from a live instance, not transcribed from the models.

## Conventions

- **Content type** — `application/json` for all requests and responses, except `POST /items`, which
  is `multipart/form-data` because it carries the image files, and `204`, which has an empty body.
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
      {"type": "missing", "loc": ["body", "images"], "msg": "Field required", "input": null}
    ]
  }
}
```

| Status | `code` | Cause |
|---|---|---|
| 404 | `not_found` | no item with that id |
| 409 | `conflict` | defined in `app/core/exceptions.py`, not yet raised anywhere |
| 422 | `validation_error` | body, query, or path validation failed, or an upload was rejected |
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

`multipart/form-data` carrying **only the image files**. There are no item detail fields: an item is
created from its photos and described afterwards with `PATCH`.
**At least one image is required** — an item cannot be created without a photo.

| Field | Type | Required | Constraints |
|---|---|---|---|
| `images` | file (repeatable) | **yes** | 1–`IMAGE_MAX_COUNT` files, each ≤ `IMAGE_MAX_BYTES` and of an `IMAGE_ALLOWED_CONTENT_TYPES` type |

`name`, `category`, `color`, `brand`, `size` and `notes` are **not accepted here** and come back `null`.
Send them to `PATCH /items/{item_id}` once the item exists.

Each file is uploaded to S3 under `items/{item_id}/{image_id}{ext}` before the row is written. The
bucket stays private: the key is what is stored, and every read presigns a fresh GET URL.

```bash
curl -X POST localhost:8000/api/v1/items \
  -F images=@coat-front.jpg -F images=@coat-back.jpg
```

**201** — the full `ItemRead` object. Every detail field comes back explicitly `null`, and `images`
carries one entry per uploaded file, in upload order:

```json
{
  "name": null,
  "category": null,
  "color": null,
  "brand": null,
  "size": null,
  "notes": null,
  "id": "ea899ad1-659c-4b3a-a2d6-1715e6df3943",
  "created_at": "2026-08-26T10:01:34.166424Z",
  "updated_at": "2026-08-26T10:01:34.166424Z",
  "images": [
    {
      "id": "e30207dc-6801-4009-8596-168a11fc02fc",
      "url": "https://lokara-wardrobe.s3.ap-south-1.amazonaws.com/items/ea899ad1-.../e30207dc-....jpg?X-Amz-Algorithm=...&X-Amz-Expires=3600&X-Amz-Signature=...",
      "content_type": "image/jpeg",
      "size_bytes": 208,
      "created_at": "2026-08-26T10:01:34.166424Z"
    },
    {
      "id": "8b9e01fc-e19f-4511-8fe3-f14818c694fd",
      "url": "https://lokara-wardrobe.s3.ap-south-1.amazonaws.com/items/ea899ad1-.../8b9e01fc-....jpg?X-Amz-Algorithm=...&X-Amz-Expires=3600&X-Amz-Signature=...",
      "content_type": "image/jpeg",
      "size_bytes": 208,
      "created_at": "2026-08-26T10:01:34.166424Z"
    }
  ]
}
```

(The two `url` values above are abbreviated; every other value is a live capture. The query string is a
SigV4 signature that expires after `S3_PRESIGN_EXPIRY_SECONDS` — the URL is not stable and must not be
persisted by clients.)

`created_at` and `updated_at` are identical on creation.

**422** — missing or invalid fields. Schema failures carry the usual `details` array; upload rules are
enforced in the service layer and report a plain message instead:

```json
{"error": {"code": "validation_error", "message": "'notes.pdf' is application/pdf; allowed types are image/jpeg, image/png, image/webp."}}
```

Omitting the `images` part entirely is caught earlier, by FastAPI:

```json
{"error": {"code": "validation_error", "message": "Request validation failed.",
 "details": [{"type": "missing", "loc": ["body", "images"], "msg": "Field required", "input": null}]}}
```

> **Unknown fields are silently ignored.** Extra form fields are discarded with no warning. Since the
> detail fields moved to `PATCH`, a client still sending `-F name=...` here gets a `201` and an item
> whose `name` is `null`.

> **A failed upload can orphan objects.** Files are pushed to S3 before the row is written; if the
> request then fails, the transaction rolls back but the already-uploaded objects stay in the bucket.
> There is no reaper — an S3 lifecycle rule on unreferenced keys is the usual answer.

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
    "updated_at": "2026-08-24T07:03:11.948765Z",
    "images": [{"id": "...", "url": "https://...", "content_type": "image/png",
                "size_bytes": 208, "created_at": "2026-08-24T07:03:11.948765Z"}]
  }
]

Every read presigns the URLs of every image it returns, so a large `limit` costs one signing pass per
image. Signing is local (no S3 round trip), but it is not free.
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

True partial update — only fields present in the body are applied (`exclude_unset=True`). Every
detail field is optional here, with the same length constraints; `name` and `category` remain
non-empty when supplied. This is the only way to set them — `POST` does not accept them.

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

The item's rows in `item_images` go with it (`ON DELETE CASCADE`), and its objects are deleted from S3
after the row delete flushes. If that S3 call fails the request 500s and the transaction rolls back, so
the item survives — the failure mode is a retry, never a row pointing at a deleted object.

## Response object — `ItemRead`

```
name, category, color, brand, size, notes, id, created_at, updated_at, images[]
```

Each entry of `images` is an `ItemImageRead`: `id`, `url`, `content_type`, `size_bytes`, `created_at`.
`url` is **derived, not stored** — it is presigned per response and expires.

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
- **Images are write-once.** They can only be attached at creation: `PATCH` ignores them and there is no
  endpoint to add, replace, reorder, or remove an individual image.
- **Uploads are buffered in memory.** Each file is read fully before the size check, so the
  `IMAGE_MAX_BYTES` limit bounds what is stored, not what is received.

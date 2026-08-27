# Database

PostgreSQL 16, accessed asynchronously through SQLAlchemy 2.0 + asyncpg. Schema is owned entirely by
Alembic — the application never creates tables.

Everything below was verified against a live database at revision `ccb99601b904`.

## Current schema

Three tables: `wardrobe_items` and `item_images` (application data) and `alembic_version` (migration
bookkeeping).

One relationship exists: `item_images.item_id` → `wardrobe_items.id`, `ON DELETE CASCADE`. It follows
the rules in [Adding the first relationship](#adding-the-first-relationship) — eager loading and a
database-enforced delete rule.

### `wardrobe_items`

Defined by `app/models/item.py` plus the mixins in `app/db/base.py`.

| Column | Type | Null | Default | Notes |
|---|---|---|---|---|
| `id` | `uuid` | not null | — | PK, generated in Python (`uuid4`) |
| `name` | `varchar(120)` | null | — | indexed; null until set via `PATCH` |
| `category` | `varchar(50)` | null | — | indexed, free-text (no enum/FK); null until set via `PATCH` |
| `color` | `varchar(40)` | null | — | |
| `brand` | `varchar(80)` | null | — | |
| `size` | `varchar(20)` | null | — | |
| `notes` | `text` | null | — | unbounded |
| `created_at` | `timestamptz` | not null | `now()` | |
| `updated_at` | `timestamptz` | not null | `now()` | see caveat below |

Indexes:

```
wardrobe_items_pkey          UNIQUE btree (id)
ix_wardrobe_items_category   btree (category)
ix_wardrobe_items_name       btree (name)
```

`category` is indexed because it is the only filter the list endpoint exposes. `name` is indexed
ahead of search. Note that list results are ordered by `created_at DESC`, which is **not** indexed —
fine at current scale, but the first thing to add if listing slows down.

### `item_images`

Defined by `app/models/image.py`. One row per image uploaded with an item.

| Column | Type | Null | Default | Notes |
|---|---|---|---|---|
| `id` | `uuid` | not null | — | PK, generated in Python (`uuid4`); also names the S3 object |
| `item_id` | `uuid` | not null | — | FK → `wardrobe_items.id`, `ON DELETE CASCADE`, indexed |
| `s3_key` | `varchar(512)` | not null | — | unique; `items/{item_id}/{image_id}{ext}` |
| `content_type` | `varchar(100)` | not null | — | as sent by the client, restricted to the allowed list |
| `size_bytes` | `integer` | not null | — | byte length of the uploaded file |
| `position` | `integer` | not null | — | upload order; the relationship's `order_by` |
| `created_at` | `timestamptz` | not null | `now()` | |
| `updated_at` | `timestamptz` | not null | `now()` | |

Indexes:

```
item_images_pkey          UNIQUE btree (id)
item_images_s3_key_key    UNIQUE btree (s3_key)
ix_item_images_item_id    btree (item_id)
```

**The bucket is not transactional.** Objects are written before the row and deleted after it, so a
rolled-back request can leave an unreferenced object behind. The database is the source of truth about
which objects matter; unreferenced keys need an S3 lifecycle rule to clean up. No URL is stored — only
the key — so rotating buckets or regions is a config change, not a data migration.

### `alembic_version`

Alembic's own table: a single `varchar(32)` column, `version_num`, holding exactly one row — the
revision the database is currently at. Never edit it by hand; use `alembic stamp` if you must correct
it.

## Column semantics worth knowing

### `updated_at` is maintained by SQLAlchemy, not by the database

There is **no trigger**. `server_default=now()` populates both timestamps on insert, but
`onupdate=func.now()` is an ORM-level instruction: SQLAlchemy injects `now()` into `UPDATE` statements
*it* generates. Verified directly:

```sql
UPDATE wardrobe_items SET name = 'probe2' WHERE name = 'probe';
-- created_at = updated_at still true → updated_at did NOT advance
```

Consequences:

- Writes through the repository layer maintain `updated_at` correctly.
- Raw SQL, `psql`, bulk `UPDATE` statements, and data-migration scripts **silently leave it stale**.
- If you need the guarantee to hold regardless of write path, add a `BEFORE UPDATE` trigger in a
  migration. Until then, treat `updated_at` as "last modified through the API".

### Primary keys are client-generated

`uuid4` is produced in Python before insert, not by the database. An object therefore has its identity
before it is flushed, which is what lets the repository return a usable object without a round-trip
for the key. There is no sequence and no `gen_random_uuid()` default in the DDL.

The model uses `sa.Uuid`, the dialect-agnostic type — it renders as native `uuid` on PostgreSQL (as
the live schema confirms) while keeping models loadable under SQLite.

## How migrations work

`alembic/env.py` is async and deviates from the stock template in three ways:

1. **The URL comes from `settings.database_url`**, not from `sqlalchemy.url` in `alembic.ini` — that
   key is deliberately absent. Migrations therefore target whatever `DATABASE_URL` points at, exactly
   like the application. One source of truth.
2. **It runs through `create_async_engine`**, with `connection.run_sync(do_run_migrations)` bridging
   Alembic's synchronous API onto the async connection.
3. **It does `from app.models import *`** so autogenerate can see the tables.

That last point is the sharpest edge in this system:

> A new model **must** be exported from `app/models/__init__.py`. If it is not imported there, its
> table is absent from `Base.metadata`, and `--autogenerate` produces an **empty migration with no
> error**. The failure is silent.

`compare_type=True` is enabled, so column type changes are detected rather than skipped.

### Workflow

```bash
# 1. edit the model, and export it from app/models/__init__.py
# 2. generate
.venv/Scripts/python.exe -m alembic revision --autogenerate -m "add whatever"
# 3. READ the generated file — autogenerate suggests, it does not decide
# 4. apply
.venv/Scripts/python.exe -m alembic upgrade head
```

Always generate against **PostgreSQL**. The dialect leaks into the file: the same model produces
`server_default=sa.text('now()')` on Postgres and `sa.text('(CURRENT_TIMESTAMP)')` on SQLite.

### Inspection and safety commands

```bash
alembic current    # revision the DB is at        → ccb99601b904 (head)
alembic history    # revision graph               → <base> -> ccb99601b904 (head), initial
alembic check      # do models and migrations agree?
alembic downgrade -1
alembic stamp head # mark as migrated without running (recovery only)
```

`alembic check` is the one to reach for in CI — it exits non-zero when models have drifted from
migrations, catching the "forgot to generate a migration" class of bug. Currently clean: *No new
upgrade operations detected.*

### What autogenerate will not catch

Detection is metadata-level. It does not see, and will not write, migrations for: data backfills,
`CHECK` constraints, triggers, functions, or most server-default changes. Write those by hand with
`op.execute()`.

### Reversibility

The initial migration has a real `downgrade()`, and the round-trip is verified — `downgrade base`
drops `wardrobe_items` leaving only `alembic_version`; `upgrade head` restores the table with both
indexes intact. Keep this property: autogenerated downgrades are usually correct for schema changes
but are always wrong for data migrations, which you must reverse deliberately or explicitly refuse to.

## Databases and environments

`DATABASE_URL` is the only thing distinguishing environments — see [ARCHITECTURE.md](ARCHITECTURE.md).
Locally there are two databases on the same server:

| Database | Purpose | Created by |
|---|---|---|
| `lokara_wardrobe` | development | compose `POSTGRES_DB` |
| `lokara_wardrobe_test` | test runs | `scripts/create_test_db.sh` |

The test database is **dropped and recreated** on every run — `tests/conftest.py` calls
`Base.metadata.drop_all` / `create_all` against `TEST_DATABASE_URL`. Two consequences:

- Pointing `TEST_DATABASE_URL` at your development database will destroy it.
- Tests build the schema from **models**, not from migrations. A migration that diverges from the
  models will not be caught by the test suite — `alembic check` is what catches that.

`scripts/create_test_db.sh` runs from `/docker-entrypoint-initdb.d/` and therefore executes **only on
first initialization of the `pgdata` volume**. If the volume already exists, the script is skipped;
create the database manually:

```bash
docker compose exec db psql -U postgres -c "CREATE DATABASE lokara_wardrobe_test;"
```

`docker compose down -v` destroys the volume and every applied migration with it. Plain `down` is safe.

## Adding a table

1. Create the model in `app/models/`, composing `UUIDMixin` and `TimestampMixin` from `app/db/base.py`.
2. Export it from `app/models/__init__.py` — non-negotiable, per the silent-failure note above.
3. Autogenerate, read the migration, apply.

Keep `sort_order` in mind: the mixins set `-100` on `id` and `100` on the timestamps so inherited
columns bracket the model's own rather than trailing them.

## Adding the first relationship

No foreign keys exist yet, so this is greenfield. Two things to get right:

**Lazy loading raises under async.** The default `lazy="select"` triggers IO on attribute access, which
async SQLAlchemy cannot do implicitly — you get `MissingGreenlet`, often only in a code path that
happens to touch the attribute. Load relationships eagerly and explicitly in the repository:

```python
stmt = select(WardrobeItem).options(selectinload(WardrobeItem.tags))
```

Set `lazy="raise"` on the relationship to convert the failure into a loud, immediate error at
development time rather than a surprise in production.

**Decide the delete behavior in the schema**, not in Python. Pass `ondelete="CASCADE"` (or
`"RESTRICT"`) to `ForeignKey` so the database enforces it; ORM-level `cascade` alone leaves raw SQL
and bulk deletes free to violate the intent — the same class of gap as `updated_at` above.

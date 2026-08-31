"""Fill in embeddings for analyses stored before the vector column existed.

Rows analyzed before the `embedding` column was added, and rows whose embedding
call failed at analysis time, sit at `embedding IS NULL` forever: the only writer
is `ItemService.analyze_item`, reachable solely from the upload background task.
A null vector means the item can never appear in search results.

This re-renders each stored analysis with the same `analysis_to_text` the write
path uses, so backfilled vectors land in the same space as new ones. No vision
call is made — the analysis is already on the row.

Run it once, against the database `DATABASE_URL` points at:

    .venv/Scripts/python.exe -m scripts.backfill_embeddings
"""

import asyncio
import logging

from sqlalchemy import select

from app.api.deps import get_item_embedder
from app.db.session import SessionFactory
from app.embeddings.text import analysis_to_text
from app.models.analysis import ItemAnalysis
from app.schemas.analysis import ItemAnalysisResult

logger = logging.getLogger("backfill_embeddings")


async def backfill() -> int:
    """Embed every analysis missing a vector. Returns the number that failed."""
    embedder = get_item_embedder()
    if embedder is None:
        print("EMBEDDINGS_ENABLED is false — nothing to do.")
        return 0

    # Owns its own transaction, exactly like `get_session` does for a request and
    # `_run_analysis` does for the background task.
    async with SessionFactory() as session:
        try:
            result = await session.execute(
                select(ItemAnalysis).where(ItemAnalysis.embedding.is_(None))
            )
            rows = list(result.scalars().all())
            print(f"found {len(rows)} analyses without an embedding")

            embedded = 0
            failed = 0
            for row in rows:
                try:
                    text = analysis_to_text(ItemAnalysisResult.model_validate(row))
                    row.embedding = await embedder.embed(text)
                except Exception as exc:  # noqa: BLE001 - one bad row must not
                    # abandon the rest; it stays null and a re-run retries it.
                    logger.warning("embedding failed for item %s", row.item_id, exc_info=exc)
                    failed += 1
                else:
                    embedded += 1

            await session.commit()
        except Exception:
            await session.rollback()
            raise

    print(f"embedded {embedded}, failed {failed}")
    return failed


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    raise SystemExit(1 if asyncio.run(backfill()) else 0)


if __name__ == "__main__":
    main()

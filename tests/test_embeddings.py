from uuid import UUID

from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.analysis import EMBEDDING_DIMENSIONS
from app.repositories.item import ItemRepository
from app.services.item import ItemService
from app.storage.base import ImageUpload
from tests.conftest import FakeImageStorage, FakeItemAnalyzer, FakeItemEmbedder

ITEMS = f"{settings.api_v1_prefix}/items"

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64


def image(name: str = "shirt.png", content_type: str = "image/png") -> tuple:
    return ("images", (name, PNG, content_type))


async def _embedding_dims(session: AsyncSession, item_id: str) -> int | None:
    """Read the stored vector's width straight from Postgres.

    Going through SQL rather than the ORM attribute proves the value really
    landed in a `vector` column, not just in the identity map.
    """
    result = await session.execute(
        text("SELECT vector_dims(embedding) FROM item_analysis WHERE item_id = :id"),
        {"id": UUID(item_id)},
    )
    return result.scalar_one()


async def test_ready_analysis_stores_a_vector(
    client: AsyncClient, session: AsyncSession, embedder: FakeItemEmbedder
) -> None:
    created = await client.post(ITEMS, files=[image()])
    item_id = created.json()["id"]

    assert (await client.get(f"{ITEMS}/{item_id}")).json()["analysis_status"] == "ready"
    assert len(embedder.calls) == 1
    assert await _embedding_dims(session, item_id) == EMBEDDING_DIMENSIONS


async def test_embedding_failure_keeps_the_analysis(
    client: AsyncClient, session: AsyncSession, embedder: FakeItemEmbedder
) -> None:
    """The vision result cost a model call; an embeddings outage must not lose it."""
    embedder.error = RuntimeError("embeddings unavailable")

    created = await client.post(ITEMS, files=[image()])
    item_id = created.json()["id"]

    body = (await client.get(f"{ITEMS}/{item_id}")).json()
    assert body["analysis_status"] == "ready"
    assert body["analysis_error"] is None
    assert body["analysis"] is not None
    assert await _embedding_dims(session, item_id) is None


async def test_embeddings_can_be_switched_off(
    session: AsyncSession, storage: FakeImageStorage, analyzer: FakeItemAnalyzer
) -> None:
    """`get_item_embedder` returns None when EMBEDDINGS_ENABLED is false."""
    service = ItemService(ItemRepository(session), storage, analyzer, None)
    item = await service.create_item(
        [ImageUpload(filename="shirt.png", content_type="image/png", data=PNG)]
    )

    analyzed = await service.analyze_item(item.id)

    assert analyzed.analysis_status == "ready"
    assert analyzed.analysis is not None
    assert await _embedding_dims(session, str(item.id)) is None


async def test_embedded_text_carries_the_garment_not_the_row(
    client: AsyncClient, embedder: FakeItemEmbedder
) -> None:
    """Only the 29 analysis fields are embedded — no ids, no timestamps."""
    created = await client.post(ITEMS, files=[image()])
    item_id = created.json()["id"]

    embedded = embedder.calls[0]
    assert "Beige Linen Shirt" in embedded
    assert "Category: Shirt" in embedded
    assert "Tags: breathable, summer-staple, neutral" in embedded

    assert item_id not in embedded
    assert "created_at" not in embedded
    assert "updated_at" not in embedded
    # brand_guess is None in the fixture: the line is dropped, not rendered null.
    assert "Brand:" not in embedded

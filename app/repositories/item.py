from collections.abc import Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.analysis import ItemAnalysis
from app.models.image import ItemImage
from app.models.item import WardrobeItem


class ItemRepository:
    """Data access only. Never commits — the session dependency owns the transaction."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, item_id: UUID) -> WardrobeItem | None:
        return await self.session.get(WardrobeItem, item_id)

    async def search_by_embedding(
        self, embedding: Sequence[float], *, limit: int, offset: int
    ) -> list[tuple[WardrobeItem, float]]:
        """Items nearest the given vector, closest first, with their distance.

        Ordering is by cosine distance so `ix_item_analysis_embedding` — built
        with `vector_cosine_ops` — is usable; L2 or inner product would not hit it.

        The join drops items with no analysis row at all, and the explicit null
        check drops analyzed items whose embedding call failed: Postgres sorts
        nulls last but they would still occupy result slots.

        Declared above `list` on purpose — once that name is bound in the class
        body, the `list[...]` in this annotation would resolve to the method.
        """
        distance = ItemAnalysis.embedding.cosine_distance(embedding).label("distance")
        stmt = (
            select(WardrobeItem, distance)
            .join(ItemAnalysis, ItemAnalysis.item_id == WardrobeItem.id)
            .where(ItemAnalysis.embedding.is_not(None))
            .order_by(distance)
            .limit(limit)
            .offset(offset)
        )
        result = await self.session.execute(stmt)
        return [(item, distance) for item, distance in result.all()]

    async def list(
        self, *, limit: int, offset: int, category: str | None = None
    ) -> list[WardrobeItem]:
        stmt = select(WardrobeItem).order_by(WardrobeItem.created_at.desc())
        if category is not None:
            stmt = stmt.where(WardrobeItem.category == category)
        result = await self.session.execute(stmt.limit(limit).offset(offset))
        return list(result.scalars().all())

    async def create(
        self, data: dict[str, Any], images: Sequence[dict[str, Any]] = ()
    ) -> WardrobeItem:
        item = WardrobeItem(**data, images=[ItemImage(**image) for image in images])
        self.session.add(item)
        await self.session.flush()
        await self.session.refresh(item)
        return item

    async def update(self, item: WardrobeItem, data: dict[str, Any]) -> WardrobeItem:
        for field, value in data.items():
            setattr(item, field, value)
        await self.session.flush()
        await self.session.refresh(item)
        return item

    async def set_analysis(
        self, item: WardrobeItem, data: dict[str, Any]
    ) -> WardrobeItem:
        """Write the item's analysis row, replacing any earlier one.

        delete-orphan on the relationship deletes the previous row, so a re-run
        never leaves two.
        """
        item.analysis = ItemAnalysis(**data)
        await self.session.flush()
        await self.session.refresh(item)
        return item

    async def delete(self, item: WardrobeItem) -> None:
        await self.session.delete(item)
        await self.session.flush()

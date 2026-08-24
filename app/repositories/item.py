from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.item import WardrobeItem


class ItemRepository:
    """Data access only. Never commits — the session dependency owns the transaction."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, item_id: UUID) -> WardrobeItem | None:
        return await self.session.get(WardrobeItem, item_id)

    async def list(
        self, *, limit: int, offset: int, category: str | None = None
    ) -> list[WardrobeItem]:
        stmt = select(WardrobeItem).order_by(WardrobeItem.created_at.desc())
        if category is not None:
            stmt = stmt.where(WardrobeItem.category == category)
        result = await self.session.execute(stmt.limit(limit).offset(offset))
        return list(result.scalars().all())

    async def create(self, data: dict[str, Any]) -> WardrobeItem:
        item = WardrobeItem(**data)
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

    async def delete(self, item: WardrobeItem) -> None:
        await self.session.delete(item)
        await self.session.flush()

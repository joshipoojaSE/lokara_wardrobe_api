from uuid import UUID

from app.core.exceptions import NotFoundError
from app.models.item import WardrobeItem
from app.repositories.item import ItemRepository
from app.schemas.item import ItemCreate, ItemUpdate


class ItemService:
    """Business rules. Knows nothing about HTTP."""

    def __init__(self, repo: ItemRepository) -> None:
        self.repo = repo

    async def get_item(self, item_id: UUID) -> WardrobeItem:
        item = await self.repo.get(item_id)
        if item is None:
            raise NotFoundError(f"Wardrobe item {item_id} not found.")
        return item

    async def list_items(
        self, *, limit: int, offset: int, category: str | None = None
    ) -> list[WardrobeItem]:
        return await self.repo.list(limit=limit, offset=offset, category=category)

    async def create_item(self, payload: ItemCreate) -> WardrobeItem:
        return await self.repo.create(payload.model_dump())

    async def update_item(self, item_id: UUID, payload: ItemUpdate) -> WardrobeItem:
        item = await self.get_item(item_id)
        return await self.repo.update(item, payload.model_dump(exclude_unset=True))

    async def delete_item(self, item_id: UUID) -> None:
        item = await self.get_item(item_id)
        await self.repo.delete(item)

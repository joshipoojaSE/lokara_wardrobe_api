from uuid import UUID

from fastapi import APIRouter, Query, status

from app.api.deps import ItemServiceDep
from app.schemas.item import ItemCreate, ItemRead, ItemUpdate

router = APIRouter(prefix="/items", tags=["items"])


@router.post("", response_model=ItemRead, status_code=status.HTTP_201_CREATED)
async def create_item(payload: ItemCreate, service: ItemServiceDep) -> ItemRead:
    return await service.create_item(payload)


@router.get("", response_model=list[ItemRead])
async def list_items(
    service: ItemServiceDep,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    category: str | None = Query(default=None),
) -> list[ItemRead]:
    return await service.list_items(limit=limit, offset=offset, category=category)


@router.get("/{item_id}", response_model=ItemRead)
async def get_item(item_id: UUID, service: ItemServiceDep) -> ItemRead:
    return await service.get_item(item_id)


@router.patch("/{item_id}", response_model=ItemRead)
async def update_item(
    item_id: UUID, payload: ItemUpdate, service: ItemServiceDep
) -> ItemRead:
    return await service.update_item(item_id, payload)


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_item(item_id: UUID, service: ItemServiceDep) -> None:
    await service.delete_item(item_id)

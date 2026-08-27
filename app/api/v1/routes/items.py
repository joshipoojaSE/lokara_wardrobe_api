from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, File, Query, UploadFile, status

from app.api.deps import ItemServiceDep
from app.schemas.item import ItemRead, ItemUpdate
from app.storage.base import ImageUpload

router = APIRouter(prefix="/items", tags=["items"])


@router.post("", response_model=ItemRead, status_code=status.HTTP_201_CREATED)
async def create_item(
    service: ItemServiceDep,
    images: Annotated[list[UploadFile], File(description="One or more image files.")],
) -> ItemRead:
    """multipart/form-data carrying the image files and nothing else.

    The item is created undescribed — name, category and the rest come back null
    and are filled in with PATCH.
    """
    uploads = [
        ImageUpload(
            filename=image.filename or "",
            content_type=image.content_type or "",
            data=await image.read(),
        )
        for image in images
        if image.filename
    ]
    return await service.create_item(uploads)


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

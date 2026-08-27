from collections.abc import Sequence
from pathlib import PurePosixPath
from typing import Any
from uuid import UUID, uuid4

from app.core.config import settings
from app.core.exceptions import NotFoundError, ValidationError
from app.models.item import WardrobeItem
from app.repositories.item import ItemRepository
from app.schemas.item import ItemBase, ItemImageRead, ItemRead, ItemUpdate
from app.storage.base import ImageStorage, ImageUpload

_EXTENSIONS = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}


class ItemService:
    """Business rules. Knows nothing about HTTP."""

    def __init__(self, repo: ItemRepository, storage: ImageStorage) -> None:
        self.repo = repo
        self.storage = storage

    async def get_item(self, item_id: UUID) -> ItemRead:
        return self._to_read(await self._get_model(item_id))

    async def list_items(
        self, *, limit: int, offset: int, category: str | None = None
    ) -> list[ItemRead]:
        items = await self.repo.list(limit=limit, offset=offset, category=category)
        return [self._to_read(item) for item in items]

    async def create_item(self, images: Sequence[ImageUpload]) -> ItemRead:
        """Create an item from its images. Its details start out null."""
        self._validate_images(images)

        # The id is minted here so uploaded objects can be keyed by item before
        # the row exists. If an upload fails, the session rolls back and no row
        # is written; objects already in S3 for this request are then orphaned.
        item_id = uuid4()
        records: list[dict[str, Any]] = []
        for position, upload in enumerate(images):
            image_id = uuid4()
            key = f"items/{item_id}/{image_id}{_extension_for(upload)}"
            await self.storage.upload(key=key, upload=upload)
            records.append(
                {
                    "id": image_id,
                    "s3_key": key,
                    "content_type": upload.content_type,
                    "size_bytes": upload.size_bytes,
                    "position": position,
                }
            )

        item = await self.repo.create({"id": item_id}, records)
        return self._to_read(item)

    async def update_item(self, item_id: UUID, payload: ItemUpdate) -> ItemRead:
        item = await self._get_model(item_id)
        updated = await self.repo.update(item, payload.model_dump(exclude_unset=True))
        return self._to_read(updated)

    async def delete_item(self, item_id: UUID) -> None:
        item = await self._get_model(item_id)
        keys = [image.s3_key for image in item.images]
        await self.repo.delete(item)
        await self.storage.delete(keys)

    async def _get_model(self, item_id: UUID) -> WardrobeItem:
        item = await self.repo.get(item_id)
        if item is None:
            raise NotFoundError(f"Wardrobe item {item_id} not found.")
        return item

    def _validate_images(self, images: Sequence[ImageUpload]) -> None:
        if not images:
            raise ValidationError("At least one image file is required.")
        if len(images) > settings.image_max_count:
            raise ValidationError(
                f"At most {settings.image_max_count} images may be uploaded at once."
            )
        for upload in images:
            if upload.content_type not in settings.image_allowed_content_types:
                allowed = ", ".join(settings.image_allowed_content_types)
                raise ValidationError(
                    f"{upload.filename!r} is {upload.content_type or 'untyped'}; "
                    f"allowed types are {allowed}."
                )
            if upload.size_bytes == 0:
                raise ValidationError(f"{upload.filename!r} is empty.")
            if upload.size_bytes > settings.image_max_bytes:
                raise ValidationError(
                    f"{upload.filename!r} is larger than the "
                    f"{settings.image_max_bytes} byte limit."
                )

    def _to_read(self, item: WardrobeItem) -> ItemRead:
        return ItemRead(
            id=item.id,
            created_at=item.created_at,
            updated_at=item.updated_at,
            images=[
                ItemImageRead(
                    id=image.id,
                    url=self.storage.url_for(image.s3_key),
                    content_type=image.content_type,
                    size_bytes=image.size_bytes,
                    created_at=image.created_at,
                )
                for image in item.images
            ],
            **ItemBase.model_validate(item).model_dump(),
        )


def _extension_for(upload: ImageUpload) -> str:
    suffix = PurePosixPath(upload.filename).suffix.lower()
    if suffix in _EXTENSIONS.values():
        return suffix
    return _EXTENSIONS.get(upload.content_type, "")

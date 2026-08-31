import logging
from collections.abc import Sequence
from pathlib import PurePosixPath
from typing import Any
from uuid import UUID, uuid4

from app.analysis.base import ItemAnalyzer
from app.core.config import settings
from app.core.exceptions import EmbeddingError, NotFoundError, ValidationError
from app.embeddings.base import ItemEmbedder
from app.embeddings.text import analysis_to_text
from app.models.item import WardrobeItem
from app.repositories.item import ItemRepository
from app.schemas.analysis import ItemAnalysisResult
from app.schemas.item import (
    ItemBase,
    ItemImageRead,
    ItemRead,
    ItemSearchResult,
    ItemUpdate,
)
from app.storage.base import ImageStorage, ImageUpload

logger = logging.getLogger(__name__)

_EXTENSIONS = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}


class ItemService:
    """Business rules. Knows nothing about HTTP."""

    def __init__(
        self,
        repo: ItemRepository,
        storage: ImageStorage,
        analyzer: ItemAnalyzer | None = None,
        embedder: ItemEmbedder | None = None,
    ) -> None:
        self.repo = repo
        self.storage = storage
        self.analyzer = analyzer
        self.embedder = embedder

    async def get_item(self, item_id: UUID) -> ItemRead:
        return self._to_read(await self._get_model(item_id))

    async def list_items(
        self, *, limit: int, offset: int, category: str | None = None
    ) -> list[ItemRead]:
        items = await self.repo.list(limit=limit, offset=offset, category=category)
        return [self._to_read(item) for item in items]

    async def search_items(
        self, query: str, *, limit: int, offset: int
    ) -> list[ItemSearchResult]:
        """Rank items by how close their analysis sits to a natural-language query.

        The query is embedded with the same model that produced the stored
        vectors, so both live in one space.

        Unlike `_embed`, an embedding failure is not swallowed here: there the
        vector is a bonus on top of an analysis worth keeping, whereas here it
        *is* the request, and an empty result would misreport an outage as "no
        matches".
        """
        text = query.strip()
        if not text:
            raise ValidationError("Search query must not be empty.")
        if self.embedder is None:
            raise EmbeddingError("Search is unavailable: embeddings are disabled.")

        vector = await self.embedder.embed(text)
        rows = await self.repo.search_by_embedding(vector, limit=limit, offset=offset)
        return [
            ItemSearchResult(score=1.0 - distance, item=self._to_read(item))
            for item, distance in rows
        ]

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

        status = "pending" if settings.analysis_enabled else "skipped"
        item = await self.repo.create(
            {"id": item_id, "analysis_status": status}, records
        )
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

    async def analyze_item(self, item_id: UUID) -> ItemRead:
        """Describe an item with the vision model and store the result.

        Runs after the response has been sent, so it never raises: a failure is
        recorded on the item as `analysis_status="failed"` and left there for a
        retry rather than lost in a background stack trace.
        """
        item = await self._get_model(item_id)
        if self.analyzer is None:
            return self._to_read(item)

        try:
            images = [
                await self.storage.download(image.s3_key) for image in item.images
            ]
            result = await self.analyzer.analyze(images)
        except Exception as exc:  # noqa: BLE001 - recorded on the row, not raised
            logger.warning("analysis failed for item %s", item_id, exc_info=exc)
            failed = await self.repo.update(
                item, {"analysis_status": "failed", "analysis_error": str(exc)}
            )
            return self._to_read(failed)

        # Outside the try above on purpose: an embeddings outage must not set
        # `analysis_status="failed"` and throw away a vision result that cost a
        # model call to produce.
        embedding = await self._embed(result)
        await self.repo.set_analysis(
            item, result.model_dump() | {"embedding": embedding}
        )
        updated = await self.repo.update(
            item, {"analysis_status": "ready", "analysis_error": None}
        )
        return self._to_read(updated)

    async def _embed(self, result: ItemAnalysisResult) -> list[float] | None:
        """Best-effort. A missing vector costs searchability, not the analysis."""
        if self.embedder is None:
            return None
        try:
            return await self.embedder.embed(analysis_to_text(result))
        except Exception as exc:  # noqa: BLE001 - logged, the analysis still stores
            logger.warning("embedding failed for %r", result.title, exc_info=exc)
            return None

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
            analysis_status=item.analysis_status,
            analysis_error=item.analysis_error,
            analysis=(
                ItemAnalysisResult.model_validate(item.analysis)
                if item.analysis is not None
                else None
            ),
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

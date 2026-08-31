from collections.abc import Awaitable, Callable
from functools import lru_cache
from typing import Annotated
from uuid import UUID

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.analysis.base import ItemAnalyzer
from app.analysis.openai import OpenAIItemAnalyzer
from app.core.config import settings
from app.db.session import SessionFactory, get_session
from app.embeddings.base import ItemEmbedder
from app.embeddings.openai import OpenAIItemEmbedder
from app.repositories.item import ItemRepository
from app.services.item import ItemService
from app.storage.base import ImageStorage
from app.storage.s3 import S3ImageStorage

DbSession = Annotated[AsyncSession, Depends(get_session)]


@lru_cache
def get_image_storage() -> ImageStorage:
    """One boto3 client per process; tests override this dependency."""
    return S3ImageStorage(
        bucket=settings.s3_bucket,
        region=settings.s3_region,
        endpoint_url=settings.s3_endpoint_url,
        access_key_id=settings.aws_access_key_id,
        secret_access_key=settings.aws_secret_access_key,
        presign_expiry_seconds=settings.s3_presign_expiry_seconds,
    )


ImageStorageDep = Annotated[ImageStorage, Depends(get_image_storage)]


@lru_cache
def get_item_analyzer() -> ItemAnalyzer | None:
    """One OpenAI client per process. None when analysis is switched off."""
    if not settings.analysis_enabled:
        return None
    return OpenAIItemAnalyzer(
        api_key=settings.openai_api_key,
        model=settings.analysis_model,
        effort=settings.analysis_effort,
        max_output_tokens=settings.analysis_max_output_tokens,
        timeout_seconds=settings.analysis_timeout_seconds,
        max_images=settings.analysis_max_images,
    )


ItemAnalyzerDep = Annotated[ItemAnalyzer | None, Depends(get_item_analyzer)]


@lru_cache
def get_item_embedder() -> ItemEmbedder | None:
    """One OpenAI client per process. None when embeddings are switched off."""
    if not settings.embeddings_enabled:
        return None
    return OpenAIItemEmbedder(
        api_key=settings.openai_api_key,
        model=settings.embedding_model,
        timeout_seconds=settings.embedding_timeout_seconds,
    )


ItemEmbedderDep = Annotated[ItemEmbedder | None, Depends(get_item_embedder)]


def get_item_service(
    session: DbSession,
    storage: ImageStorageDep,
    analyzer: ItemAnalyzerDep,
    embedder: ItemEmbedderDep,
) -> ItemService:
    return ItemService(ItemRepository(session), storage, analyzer, embedder)


ItemServiceDep = Annotated[ItemService, Depends(get_item_service)]

AnalysisRunner = Callable[[UUID], Awaitable[None]]


async def _run_analysis(item_id: UUID) -> None:
    """Background entry point: the request session is gone by the time this runs.

    Opens its own session and owns its own transaction, exactly like
    `get_session` does for a request.
    """
    async with SessionFactory() as session:
        service = ItemService(
            ItemRepository(session),
            get_image_storage(),
            get_item_analyzer(),
            get_item_embedder(),
        )
        try:
            await service.analyze_item(item_id)
            await session.commit()
        except Exception:
            await session.rollback()
            raise


def get_analysis_runner() -> AnalysisRunner:
    """Indirection so tests can point the background task at the test session."""
    return _run_analysis


AnalysisRunnerDep = Annotated[AnalysisRunner, Depends(get_analysis_runner)]

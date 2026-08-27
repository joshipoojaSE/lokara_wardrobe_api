from functools import lru_cache
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import get_session
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


def get_item_service(session: DbSession, storage: ImageStorageDep) -> ItemService:
    return ItemService(ItemRepository(session), storage)


ItemServiceDep = Annotated[ItemService, Depends(get_item_service)]

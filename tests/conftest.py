from collections.abc import AsyncIterator, Sequence

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.api.deps import get_image_storage
from app.core.config import settings
from app.db.base import Base
from app.db.session import get_session
from app.main import create_app
from app.storage.base import ImageUpload


class FakeImageStorage:
    """In-memory stand-in for S3 so tests never touch the network."""

    def __init__(self) -> None:
        self.objects: dict[str, ImageUpload] = {}

    async def upload(self, *, key: str, upload: ImageUpload) -> None:
        self.objects[key] = upload

    async def delete(self, keys: Sequence[str]) -> None:
        for key in keys:
            self.objects.pop(key, None)

    def url_for(self, key: str) -> str:
        return f"https://test-bucket.local/{key}"


@pytest.fixture(scope="session")
async def engine() -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(settings.test_database_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture
async def session(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """Each test runs inside an outer transaction that is always rolled back."""
    async with engine.connect() as connection:
        transaction = await connection.begin()
        factory = async_sessionmaker(bind=connection, expire_on_commit=False)
        async with factory() as session:
            yield session
        await transaction.rollback()


@pytest.fixture
def storage() -> FakeImageStorage:
    return FakeImageStorage()


@pytest.fixture
async def client(
    session: AsyncSession, storage: FakeImageStorage
) -> AsyncIterator[AsyncClient]:
    app = create_app()

    async def override_get_session() -> AsyncIterator[AsyncSession]:
        yield session

    app.dependency_overrides[get_session] = override_get_session
    app.dependency_overrides[get_image_storage] = lambda: storage

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client

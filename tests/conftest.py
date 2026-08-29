from collections.abc import AsyncIterator, Sequence
from dataclasses import replace
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.api.deps import get_analysis_runner, get_image_storage, get_item_analyzer
from app.core.config import settings
from app.db.base import Base
from app.db.session import get_session
from app.main import create_app
from app.repositories.item import ItemRepository
from app.schemas.analysis import ItemAnalysisResult
from app.services.item import ItemService
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

    async def download(self, key: str) -> ImageUpload:
        # Mirrors S3: the object has no original filename, so the key stands in.
        return replace(self.objects[key], filename=key)

    def url_for(self, key: str) -> str:
        return f"https://test-bucket.local/{key}"


ANALYSIS_FIXTURE = ItemAnalysisResult(
    title="Beige Linen Shirt",
    type="Top",
    category="Shirt",
    brand_guess=None,
    colors_hex=["#D8CCB4", "#EDE6D6"],
    color_family="Beige",
    material="Linen",
    fabric_weight="Light",
    fit="Regular",
    cut="Straight",
    silhouette_match="Slim or straight bottom",
    pattern="Solid",
    print_position="N/A",
    sleeve_length="Long Sleeve",
    neckline="Round",
    length="Mid",
    style_vibe="Minimalist",
    occasion="Casual",
    formality_score=5,
    wardrobe_role="Basic",
    visual_weight="Light",
    season="Summer",
    temperature_range="22°C - 32°C",
    layering_suggestion="Standalone",
    separability="Single Unit",
    harmonizing_colors_hex=[
        "#F2ECE0", "#D8CCB4", "#8C7F63", "#5A6B8C", "#D8B9A0", "#C9C2A8",
        "#FFFFF0", "#3A3A3A", "#C2A47E", "#6B5B45", "#4A6B5A", "#7A5B8C",
    ],
    harmonizing_families=[
        "Ivory", "Beige", "Olive", "Navy", "Beige", "Olive",
        "White", "Black", "Beige", "Brown", "Green", "Purple",
    ],
    pairing_suggestions=["Jeans", "Chinos", "Loafers"],
    tags=["breathable", "summer-staple", "neutral"],
)


class FakeItemAnalyzer:
    """Returns a fixed result and records what it was asked to analyze."""

    def __init__(self, error: Exception | None = None) -> None:
        self.calls: list[list[ImageUpload]] = []
        self.error = error

    async def analyze(self, images: Sequence[ImageUpload]) -> ItemAnalysisResult:
        self.calls.append(list(images))
        if self.error is not None:
            raise self.error
        return ANALYSIS_FIXTURE


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
def analyzer() -> FakeItemAnalyzer:
    return FakeItemAnalyzer()


@pytest.fixture
async def client(
    session: AsyncSession, storage: FakeImageStorage, analyzer: FakeItemAnalyzer
) -> AsyncIterator[AsyncClient]:
    app = create_app()

    async def override_get_session() -> AsyncIterator[AsyncSession]:
        yield session

    async def run_analysis(item_id: UUID) -> None:
        """Keep the background task on the test's rolled-back session.

        The real runner opens its own session, which would write outside the
        outer transaction and survive the rollback.
        """
        await ItemService(
            ItemRepository(session), storage, analyzer
        ).analyze_item(item_id)

    app.dependency_overrides[get_session] = override_get_session
    app.dependency_overrides[get_image_storage] = lambda: storage
    app.dependency_overrides[get_item_analyzer] = lambda: analyzer
    app.dependency_overrides[get_analysis_runner] = lambda: run_analysis

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client

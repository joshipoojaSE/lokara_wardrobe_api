from httpx import AsyncClient

from app.core.config import settings
from tests.conftest import ANALYSIS_FIXTURE, FakeImageStorage, FakeItemAnalyzer

ITEMS = f"{settings.api_v1_prefix}/items"

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64


def image(name: str = "shirt.png", content_type: str = "image/png") -> tuple:
    return ("images", (name, PNG, content_type))


async def test_create_item_analyzes_in_the_background(
    client: AsyncClient, analyzer: FakeItemAnalyzer
) -> None:
    """POST answers before the analysis runs; GET picks the result up."""
    created = await client.post(ITEMS, files=[image()])

    assert created.status_code == 201
    assert created.json()["analysis_status"] == "pending"
    assert created.json()["analysis"] is None

    item_id = created.json()["id"]
    fetched = await client.get(f"{ITEMS}/{item_id}")

    assert fetched.status_code == 200
    body = fetched.json()
    assert body["analysis_status"] == "ready"
    assert body["analysis_error"] is None
    assert body["analysis"] == ANALYSIS_FIXTURE.model_dump()
    assert len(body["analysis"]["harmonizing_colors_hex"]) == 12
    assert len(body["analysis"]["harmonizing_families"]) == 12
    assert len(analyzer.calls) == 1


async def test_analysis_reads_every_image_back_from_storage(
    client: AsyncClient, storage: FakeImageStorage, analyzer: FakeItemAnalyzer
) -> None:
    """The analyzer sees bytes fetched from S3, not the request's upload objects."""
    await client.post(ITEMS, files=[image("front.png"), image("back.jpg", "image/jpeg")])

    assert len(analyzer.calls) == 1
    analyzed = analyzer.calls[0]
    assert [upload.content_type for upload in analyzed] == ["image/png", "image/jpeg"]
    assert all(upload.filename in storage.objects for upload in analyzed)


async def test_failed_analysis_is_recorded_not_raised(
    client: AsyncClient, analyzer: FakeItemAnalyzer
) -> None:
    """A vision failure must not lose the item that was already created."""
    analyzer.error = RuntimeError("model unavailable")

    created = await client.post(ITEMS, files=[image()])
    assert created.status_code == 201

    body = (await client.get(f"{ITEMS}/{created.json()['id']}")).json()
    assert body["analysis_status"] == "failed"
    assert "model unavailable" in body["analysis_error"]
    assert body["analysis"] is None


async def test_analysis_does_not_fill_in_the_patchable_fields(
    client: AsyncClient,
) -> None:
    """Analysis is metadata only; name/category still come from PATCH."""
    created = await client.post(ITEMS, files=[image()])

    body = (await client.get(f"{ITEMS}/{created.json()['id']}")).json()
    assert body["analysis_status"] == "ready"
    assert body["name"] is None
    assert body["category"] is None


async def test_deleting_an_item_removes_its_analysis(client: AsyncClient) -> None:
    created = await client.post(ITEMS, files=[image()])
    item_id = created.json()["id"]
    assert (await client.get(f"{ITEMS}/{item_id}")).json()["analysis"] is not None

    assert (await client.delete(f"{ITEMS}/{item_id}")).status_code == 204
    assert (await client.get(f"{ITEMS}/{item_id}")).status_code == 404

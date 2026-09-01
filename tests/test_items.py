import io
from uuid import UUID

from httpx import AsyncClient
from PIL import Image

from app.core.config import settings
from tests.conftest import FakeImageStorage

ITEMS = f"{settings.api_v1_prefix}/items"

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64
JPEG = b"\xff\xd8\xff\xe0" + b"0" * 64

# Signatures only. The API sniffs the leading bytes but never decodes a format
# it already stores, so these do not have to be openable images.
_BYTES = {"image/png": PNG, "image/jpeg": JPEG}


def image(name: str = "shirt.png", content_type: str = "image/png") -> tuple:
    """The bytes match the declared type; a mismatch is its own test below."""
    return ("images", (name, _BYTES[content_type], content_type))


async def test_item_crud_round_trip(
    client: AsyncClient, storage: FakeImageStorage
) -> None:
    created = await client.post(
        ITEMS, files=[image("front.png"), image("back.jpg", "image/jpeg")]
    )
    assert created.status_code == 201
    body = created.json()
    item_id = body["id"]

    # Created from images alone: every describable field starts out null.
    assert body["name"] is None
    assert body["category"] is None
    assert body["color"] is None

    images = body["images"]
    assert len(images) == 2
    assert len(storage.objects) == 2
    assert sorted(key.rsplit(".", 1)[1] for key in storage.objects) == ["jpg", "png"]
    assert all(entry["url"].startswith("https://test-bucket.local/") for entry in images)
    assert images[0]["content_type"] == "image/png"
    assert images[0]["size_bytes"] == len(PNG)

    fetched = await client.get(f"{ITEMS}/{item_id}")
    assert fetched.status_code == 200
    assert fetched.json()["name"] is None
    assert [entry["id"] for entry in fetched.json()["images"]] == [
        entry["id"] for entry in images
    ]

    patched = await client.patch(
        f"{ITEMS}/{item_id}",
        json={"name": "Linen Shirt", "category": "tops", "color": "beige"},
    )
    assert patched.status_code == 200
    assert patched.json()["name"] == "Linen Shirt"
    assert patched.json()["color"] == "beige"
    assert len(patched.json()["images"]) == 2

    listed = await client.get(ITEMS, params={"category": "tops"})
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [item_id]

    deleted = await client.delete(f"{ITEMS}/{item_id}")
    assert deleted.status_code == 204
    assert storage.objects == {}

    missing = await client.get(f"{ITEMS}/{item_id}")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "not_found"


async def test_create_item_ignores_non_image_form_fields(
    client: AsyncClient, storage: FakeImageStorage
) -> None:
    """POST takes images only; stray fields are not accepted as item details."""
    created = await client.post(
        ITEMS, data={"name": "Linen Shirt", "category": "tops"}, files=[image()]
    )

    assert created.status_code == 201
    assert created.json()["name"] is None
    assert created.json()["category"] is None
    assert UUID(created.json()["id"])
    assert len(storage.objects) == 1


async def test_update_item_rejects_blank_name(client: AsyncClient) -> None:
    created = await client.post(ITEMS, files=[image()])
    item_id = created.json()["id"]

    response = await client.patch(f"{ITEMS}/{item_id}", json={"name": ""})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


async def test_create_item_requires_an_image(
    client: AsyncClient, storage: FakeImageStorage
) -> None:
    response = await client.post(
        ITEMS, files=[("images", ("", b"", "application/octet-stream"))]
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert storage.objects == {}


async def test_create_item_rejects_non_image_upload(
    client: AsyncClient, storage: FakeImageStorage
) -> None:
    response = await client.post(
        ITEMS, files=[("images", ("notes.pdf", b"%PDF-1.4", "application/pdf"))]
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert storage.objects == {}


async def test_create_item_rejects_oversized_upload(
    client: AsyncClient, storage: FakeImageStorage
) -> None:
    oversized = b"0" * (settings.image_max_bytes + 1)
    response = await client.post(
        ITEMS, files=[("images", ("huge.png", oversized, "image/png"))]
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert storage.objects == {}


def _avif_bytes() -> bytes:
    """A real AVIF. Written by hand it would be an opaque blob in the repo."""
    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), (200, 30, 40)).save(buffer, format="AVIF")
    return buffer.getvalue()


async def test_create_item_converts_avif_to_jpeg(
    client: AsyncClient, storage: FakeImageStorage
) -> None:
    """The bug this guards: browsers label a renamed AVIF `image/jpeg`.

    Stored unconverted, it reached the vision model inside a `data:image/jpeg`
    URI and OpenAI 400ed on it — long after the upload had returned 201.
    """
    avif = _avif_bytes()
    response = await client.post(
        ITEMS, files=[("images", ("photo.jpg", avif, "image/jpeg"))]
    )

    assert response.status_code == 201
    entry = response.json()["images"][0]
    assert entry["content_type"] == "image/jpeg"

    (key,) = storage.objects
    assert key.endswith(".jpg")
    stored = storage.objects[key]
    # Really transcoded, not just relabelled.
    assert stored.data != avif
    assert stored.data.startswith(b"\xff\xd8\xff")
    assert Image.open(io.BytesIO(stored.data)).format == "JPEG"
    assert entry["size_bytes"] == len(stored.data)


async def test_create_item_trusts_the_bytes_over_the_declared_type(
    client: AsyncClient, storage: FakeImageStorage
) -> None:
    """A PNG announced as `image/jpeg` is stored as what it actually is."""
    response = await client.post(
        ITEMS, files=[("images", ("mislabelled.jpg", PNG, "image/jpeg"))]
    )

    assert response.status_code == 201
    assert response.json()["images"][0]["content_type"] == "image/png"

    (key,) = storage.objects
    assert key.endswith(".png")
    assert storage.objects[key].data == PNG


async def test_create_item_rejects_bytes_that_only_claim_to_be_an_image(
    client: AsyncClient, storage: FakeImageStorage
) -> None:
    response = await client.post(
        ITEMS, files=[("images", ("shirt.png", b"not an image at all", "image/png"))]
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert storage.objects == {}

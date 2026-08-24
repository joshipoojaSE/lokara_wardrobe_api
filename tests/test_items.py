from httpx import AsyncClient

from app.core.config import settings

ITEMS = f"{settings.api_v1_prefix}/items"


async def test_item_crud_round_trip(client: AsyncClient) -> None:
    created = await client.post(
        ITEMS, json={"name": "Linen Shirt", "category": "tops", "color": "white"}
    )
    assert created.status_code == 201
    item_id = created.json()["id"]

    fetched = await client.get(f"{ITEMS}/{item_id}")
    assert fetched.status_code == 200
    assert fetched.json()["name"] == "Linen Shirt"

    listed = await client.get(ITEMS, params={"category": "tops"})
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [item_id]

    patched = await client.patch(f"{ITEMS}/{item_id}", json={"color": "beige"})
    assert patched.status_code == 200
    assert patched.json()["color"] == "beige"
    assert patched.json()["name"] == "Linen Shirt"

    deleted = await client.delete(f"{ITEMS}/{item_id}")
    assert deleted.status_code == 204

    missing = await client.get(f"{ITEMS}/{item_id}")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "not_found"


async def test_create_item_rejects_blank_name(client: AsyncClient) -> None:
    response = await client.post(ITEMS, json={"name": "", "category": "tops"})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"

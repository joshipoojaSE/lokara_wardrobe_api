from httpx import AsyncClient

from app.core.config import settings


async def test_health(client: AsyncClient) -> None:
    response = await client.get(f"{settings.api_v1_prefix}/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

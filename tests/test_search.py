from httpx import AsyncClient

from app.core.config import settings
from app.core.exceptions import EmbeddingError
from app.embeddings.text import analysis_to_text
from app.models.analysis import EMBEDDING_DIMENSIONS
from tests.conftest import ANALYSIS_FIXTURE, FakeItemEmbedder

ITEMS = f"{settings.api_v1_prefix}/items"
SEARCH = f"{ITEMS}/search"

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64

# Every item analyzes to the same fixture, so this is the text the embedder is
# handed on every upload — the key a test writes into `embedder.vectors` to place
# the next item at a chosen point in the space.
ANALYSIS_TEXT = analysis_to_text(ANALYSIS_FIXTURE)


def image(name: str = "shirt.png", content_type: str = "image/png") -> tuple:
    return ("images", (name, PNG, content_type))


def axis(index: int) -> list[float]:
    """A unit vector pointing along one dimension."""
    vector = [0.0] * EMBEDDING_DIMENSIONS
    vector[index] = 1.0
    return vector


async def create_item(client: AsyncClient, embedder: FakeItemEmbedder, vector) -> str:
    """Upload an item and pin its stored embedding to `vector`."""
    embedder.vectors[ANALYSIS_TEXT] = vector
    created = await client.post(ITEMS, files=[image()])
    assert created.status_code == 201
    return created.json()["id"]


async def test_search_ranks_by_similarity(
    client: AsyncClient, embedder: FakeItemEmbedder
) -> None:
    near = await create_item(client, embedder, axis(0))
    far = await create_item(client, embedder, axis(1))

    # Mostly along axis 0, so `near` is much closer than `far`.
    query = [0.0] * EMBEDDING_DIMENSIONS
    query[0], query[1] = 0.9, 0.1
    embedder.vectors["red tshirt"] = query

    response = await client.get(SEARCH, params={"q": "red tshirt"})

    assert response.status_code == 200
    results = response.json()
    assert [result["item"]["id"] for result in results] == [near, far]
    assert results[0]["score"] > results[1]["score"]
    # The hit carries a full item, presigned image URLs and analysis included.
    assert results[0]["item"]["analysis"]["title"] == "Beige Linen Shirt"
    assert results[0]["item"]["images"][0]["url"].startswith("https://")


async def test_search_excludes_items_without_an_embedding(
    client: AsyncClient, embedder: FakeItemEmbedder
) -> None:
    """An analysis that stored with no vector is unsearchable, not a blank hit."""
    embedder.error = RuntimeError("embeddings unavailable")
    unembedded = (await client.post(ITEMS, files=[image()])).json()["id"]
    embedder.error = None

    embedded = await create_item(client, embedder, axis(0))
    embedder.vectors["anything"] = axis(0)

    results = (await client.get(SEARCH, params={"q": "anything"})).json()

    assert [result["item"]["id"] for result in results] == [embedded]
    assert unembedded not in [result["item"]["id"] for result in results]


async def test_search_paginates(
    client: AsyncClient, embedder: FakeItemEmbedder
) -> None:
    first = await create_item(client, embedder, axis(0))
    second = await create_item(client, embedder, axis(1))
    embedder.vectors["q"] = axis(0)

    page = await client.get(SEARCH, params={"q": "q", "limit": 1})
    assert [result["item"]["id"] for result in page.json()] == [first]

    page = await client.get(SEARCH, params={"q": "q", "limit": 1, "offset": 1})
    assert [result["item"]["id"] for result in page.json()] == [second]


async def test_search_with_no_items_returns_an_empty_list(
    client: AsyncClient,
) -> None:
    response = await client.get(SEARCH, params={"q": "red tshirt"})

    assert response.status_code == 200
    assert response.json() == []


async def test_search_rejects_an_empty_query(client: AsyncClient) -> None:
    response = await client.get(SEARCH, params={"q": ""})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


async def test_search_rejects_a_whitespace_query(client: AsyncClient) -> None:
    """Long enough for the Query constraint, empty once stripped."""
    response = await client.get(SEARCH, params={"q": "   "})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


async def test_search_reports_an_embedding_outage(
    client: AsyncClient, embedder: FakeItemEmbedder
) -> None:
    """The vector is the request here, so a failure must not read as 'no matches'."""
    embedder.error = EmbeddingError("embeddings unavailable")

    response = await client.get(SEARCH, params={"q": "red tshirt"})

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "embedding_failed"


async def test_search_route_does_not_shadow_get_item(client: AsyncClient) -> None:
    """/items/search must route to search, not to /items/{item_id}."""
    response = await client.get(SEARCH, params={"q": "red tshirt"})

    assert response.status_code == 200

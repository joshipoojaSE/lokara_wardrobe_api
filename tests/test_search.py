from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import EmbeddingError
from app.embeddings.text import analysis_to_text
from app.models.analysis import EMBEDDING_DIMENSIONS
from app.repositories.item import ItemRepository
from app.schemas.answer import AnswerDraft, AnswerPick
from app.services.item import ItemService
from app.storage.base import ImageUpload
from tests.conftest import (
    ANALYSIS_FIXTURE,
    FakeImageStorage,
    FakeItemAnalyzer,
    FakeItemEmbedder,
    FakeWardrobeAnswerer,
)

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


def picks(*indexes: int) -> AnswerDraft:
    """A draft citing the given positions, so a test can see what was retrieved."""
    return AnswerDraft(
        answer="Here you go.",
        has_match=True,
        picks=[AnswerPick(index=i, reason=f"Pick {i}.") for i in indexes],
    )


async def test_search_ranks_by_similarity(
    client: AsyncClient, embedder: FakeItemEmbedder, answerer: FakeWardrobeAnswerer
) -> None:
    near = await create_item(client, embedder, axis(0))
    far = await create_item(client, embedder, axis(1))

    # Mostly along axis 0, so `near` is much closer than `far`.
    query = [0.0] * EMBEDDING_DIMENSIONS
    query[0], query[1] = 0.9, 0.1
    embedder.vectors["red tshirt"] = query
    answerer.draft = picks(1, 2)

    response = await client.get(SEARCH, params={"q": "red tshirt"})

    assert response.status_code == 200
    assert [item["item_id"] for item in response.json()["items"]] == [near, far]


async def test_each_item_carries_a_picture_a_title_and_a_reason(
    client: AsyncClient, embedder: FakeItemEmbedder, answerer: FakeWardrobeAnswerer
) -> None:
    """The response is a result card, not a dump of the analysis row."""
    item_id = await create_item(client, embedder, axis(0))
    embedder.vectors["anything"] = axis(0)
    answerer.draft = picks(1)

    item = (await client.get(SEARCH, params={"q": "anything"})).json()["items"][0]

    assert item == {
        "item_id": item_id,
        "title": "Beige Linen Shirt",
        "image_url": item["image_url"],
        "reason": "Pick 1.",
    }
    assert item["image_url"].startswith("https://")


async def test_search_excludes_items_without_an_embedding(
    client: AsyncClient, embedder: FakeItemEmbedder, answerer: FakeWardrobeAnswerer
) -> None:
    """An analysis that stored with no vector is unsearchable, not a blank hit."""
    embedder.error = RuntimeError("embeddings unavailable")
    unembedded = (await client.post(ITEMS, files=[image()])).json()["id"]
    embedder.error = None

    embedded = await create_item(client, embedder, axis(0))
    embedder.vectors["anything"] = axis(0)
    answerer.draft = picks(1, 2)

    body = (await client.get(SEARCH, params={"q": "anything"})).json()

    # Only one item was ever retrievable, so the second pick has nothing to
    # resolve against and is dropped.
    assert [item["item_id"] for item in body["items"]] == [embedded]
    assert unembedded not in [item["item_id"] for item in body["items"]]


async def test_retrieval_is_not_paginated(
    session: AsyncSession,
    storage: FakeImageStorage,
    analyzer: FakeItemAnalyzer,
    embedder: FakeItemEmbedder,
) -> None:
    """Every embedded item is ranked, so the answer window is the true top N.

    Asserted at the service, because the route only ever shows the model's
    picks — a page-2 row silently missing from retrieval would be invisible
    from the outside.
    """
    service = ItemService(ItemRepository(session), storage, analyzer, embedder)
    total = settings.answer_context_items + 3
    upload = ImageUpload(filename="shirt.png", content_type="image/png", data=PNG)
    for index in range(total):
        embedder.vectors[ANALYSIS_TEXT] = axis(index)
        item = await service.create_item([upload])
        await service.analyze_item(item.id)
    embedder.vectors["everything"] = axis(0)

    results = await service.search_items("everything")

    assert len(results) == total


async def test_search_with_no_items_answers_with_nothing_to_show(
    client: AsyncClient, answerer: FakeWardrobeAnswerer
) -> None:
    answerer.draft = AnswerDraft(
        answer="Your wardrobe is empty.", has_match=False, picks=[]
    )

    response = await client.get(SEARCH, params={"q": "red tshirt"})

    assert response.status_code == 200
    assert response.json() == {
        "answer": "Your wardrobe is empty.",
        "has_match": False,
        "items": [],
    }


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


async def test_search_ignores_removed_pagination_params(
    client: AsyncClient, embedder: FakeItemEmbedder, answerer: FakeWardrobeAnswerer
) -> None:
    """`limit`/`offset` were removed. A stale client gets an answer, not a 422.

    FastAPI ignores query parameters an endpoint does not declare, which is what
    keeps callers written against the paginated version working.
    """
    await create_item(client, embedder, axis(0))
    embedder.vectors["q"] = axis(0)
    answerer.draft = picks(1)

    response = await client.get(SEARCH, params={"q": "q", "limit": 1, "offset": 1})

    assert response.status_code == 200
    assert len(response.json()["items"]) == 1


async def test_search_route_does_not_shadow_get_item(client: AsyncClient) -> None:
    """/items/search must route to search, not to /items/{item_id}."""
    response = await client.get(SEARCH, params={"q": "red tshirt"})

    assert response.status_code == 200

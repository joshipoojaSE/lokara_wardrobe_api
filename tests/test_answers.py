from httpx import AsyncClient

from app.core.config import settings
from app.core.exceptions import AnswerError, EmbeddingError
from app.schemas.answer import AnswerDraft, AnswerPick
from tests.conftest import FakeItemEmbedder, FakeWardrobeAnswerer
from tests.test_search import ANALYSIS_TEXT, SEARCH, axis, create_item


async def test_search_returns_a_reply_and_the_items_behind_it(
    client: AsyncClient, embedder: FakeItemEmbedder, answerer: FakeWardrobeAnswerer
) -> None:
    item_id = await create_item(client, embedder, axis(0))
    embedder.vectors["red tshirt"] = axis(0)

    response = await client.get(SEARCH, params={"q": "red tshirt"})

    assert response.status_code == 200
    body = response.json()
    assert body["answer"].startswith("Your Beige Linen Shirt")
    assert body["has_match"] is True
    assert body["items"] == [
        {
            "item_id": item_id,
            "title": "Beige Linen Shirt",
            "image_url": body["items"][0]["image_url"],
            "reason": "Closest match in the wardrobe.",
        }
    ]


async def test_every_search_is_answered(
    client: AsyncClient, embedder: FakeItemEmbedder, answerer: FakeWardrobeAnswerer
) -> None:
    """There is no unanswered mode: the model runs on every query."""
    await create_item(client, embedder, axis(0))
    embedder.vectors["red tshirt"] = axis(0)

    body = (await client.get(SEARCH, params={"q": "red tshirt"})).json()

    assert len(answerer.calls) == 1
    assert set(body) == {"answer", "has_match", "items"}


async def test_the_model_only_sees_retrieved_items(
    client: AsyncClient, embedder: FakeItemEmbedder, answerer: FakeWardrobeAnswerer
) -> None:
    """Context is built from the hits, numbered, and carries their scores."""
    await create_item(client, embedder, axis(0))
    embedder.vectors["red tshirt"] = axis(0)

    await client.get(SEARCH, params={"q": "red tshirt"})

    query, context = answerer.calls[0]
    assert query == "red tshirt"
    assert context.startswith("[1] (similarity 1.00)")
    # Rendered by the same analysis_to_text the embedding was built from.
    assert "Title: Beige Linen Shirt" in context
    assert ANALYSIS_TEXT in context


async def test_context_is_capped_at_the_configured_window(
    client: AsyncClient, embedder: FakeItemEmbedder, answerer: FakeWardrobeAnswerer
) -> None:
    """More hits than the window are retrieved, but only the window is described."""
    for index in range(settings.answer_context_items + 2):
        await create_item(client, embedder, axis(index))
    embedder.vectors["everything"] = axis(0)

    await client.get(SEARCH, params={"q": "everything"})

    _, context = answerer.calls[0]
    assert context.count("(similarity") == settings.answer_context_items
    assert f"[{settings.answer_context_items}]" in context
    assert f"[{settings.answer_context_items + 1}]" not in context


async def test_a_pick_outside_the_retrieved_set_is_dropped(
    client: AsyncClient, embedder: FakeItemEmbedder, answerer: FakeWardrobeAnswerer
) -> None:
    """The one place a hallucinated reference could become a real id."""
    await create_item(client, embedder, axis(0))
    embedder.vectors["red tshirt"] = axis(0)
    answerer.draft = AnswerDraft(
        answer="Try these.",
        has_match=True,
        picks=[
            AnswerPick(index=1, reason="Real."),
            AnswerPick(index=99, reason="Invented."),
            AnswerPick(index=0, reason="Off-by-one."),
        ],
    )

    body = (await client.get(SEARCH, params={"q": "red tshirt"})).json()

    assert [item["reason"] for item in body["items"]] == ["Real."]


async def test_a_miss_is_reported_as_a_miss(
    client: AsyncClient, embedder: FakeItemEmbedder, answerer: FakeWardrobeAnswerer
) -> None:
    """Retrieval always returns its nearest rows; has_match says whether they fit."""
    item_id = await create_item(client, embedder, axis(0))
    embedder.vectors["something in green"] = axis(0)
    answerer.draft = AnswerDraft(
        answer="You don't own anything green. The closest is your beige shirt.",
        has_match=False,
        picks=[AnswerPick(index=1, reason="Nearest neutral, but not green.")],
    )

    body = (await client.get(SEARCH, params={"q": "something in green"})).json()

    assert body["has_match"] is False
    # A miss still shows the near thing — that is what the answer is describing.
    assert [item["item_id"] for item in body["items"]] == [item_id]


async def test_an_empty_wardrobe_still_answers(
    client: AsyncClient, embedder: FakeItemEmbedder, answerer: FakeWardrobeAnswerer
) -> None:
    """No hits is a question worth answering, not an error."""
    answerer.draft = AnswerDraft(
        answer="You don't have anything like that yet.", has_match=False, picks=[]
    )

    body = (await client.get(SEARCH, params={"q": "red tshirt"})).json()

    _, context = answerer.calls[0]
    assert "No items were retrieved" in context
    assert body["has_match"] is False
    assert body["items"] == []


async def test_answer_reports_a_model_outage(
    client: AsyncClient, embedder: FakeItemEmbedder, answerer: FakeWardrobeAnswerer
) -> None:
    """A missing answer must not be served as an answered search."""
    answerer.error = AnswerError("answering unavailable")

    response = await client.get(SEARCH, params={"q": "red tshirt"})

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "answer_failed"


async def test_retrieval_failure_short_circuits_the_answer(
    client: AsyncClient, embedder: FakeItemEmbedder, answerer: FakeWardrobeAnswerer
) -> None:
    """No vector means no grounding, so the model is never asked."""
    embedder.error = EmbeddingError("embeddings unavailable")

    response = await client.get(SEARCH, params={"q": "red tshirt"})

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "embedding_failed"
    assert answerer.calls == []

from datetime import datetime, timezone
from uuid import uuid4

from httpx import AsyncClient

from app.answers.context import select_window
from app.core.config import settings
from app.core.exceptions import AnswerError, EmbeddingError
from app.schemas.answer import AnswerDraft, AnswerPick
from app.schemas.item import ItemRead, ItemSearchResult
from tests.conftest import ANALYSIS_FIXTURE, FakeItemEmbedder, FakeWardrobeAnswerer
from tests.test_search import ANALYSIS_TEXT, SEARCH, axis, create_item


def hit(score: float, garment_type: str) -> ItemSearchResult:
    """A search hit of a given garment type, for the window-selection tests."""
    now = datetime.now(timezone.utc)
    return ItemSearchResult(
        score=score,
        item=ItemRead(
            id=uuid4(),
            created_at=now,
            updated_at=now,
            analysis=ANALYSIS_FIXTURE.model_copy(update={"type": garment_type}),
        ),
    )


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


# --- Window selection -------------------------------------------------------


def test_the_window_spreads_across_garment_types() -> None:
    """The reason an outfit answer has a bottom to pair with at all.

    Ranked by one query vector, every closest row here is a Top; a plain slice
    would fill all three slots with them and leave nothing to wear the shirt
    with.
    """
    hits = [hit(0.9 - index / 10, "Top") for index in range(5)]
    hits.append(hit(0.2, "Bottom"))
    hits.append(hit(0.1, "Footwear"))

    window = select_window(hits, 3)

    assert [result.item.analysis.type for result in window] == [
        "Top",
        "Bottom",
        "Footwear",
    ]


def test_the_window_keeps_the_closest_item_first() -> None:
    """Spreading types must not cost the top hit its position."""
    hits = [hit(0.9, "Top"), hit(0.8, "Bottom"), hit(0.7, "Top")]

    window = select_window(hits, 2)

    assert window[0] is hits[0]
    # Always a subsequence of the ranking, so the numbering the model cites
    # still runs closest-first.
    assert [result.score for result in window] == sorted(
        (result.score for result in window), reverse=True
    )


def test_a_single_type_wardrobe_is_the_plain_ranking() -> None:
    """With one group to round-robin over, this degenerates to hits[:limit]."""
    hits = [hit(0.9 - index / 10, "Top") for index in range(6)]

    assert select_window(hits, 4) == hits[:4]


def test_the_window_takes_everything_when_the_wardrobe_is_smaller() -> None:
    hits = [hit(0.9, "Top"), hit(0.5, "Bottom")]

    assert select_window(hits, 10) == hits
    assert select_window([], 10) == []

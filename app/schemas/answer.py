from uuid import UUID

from pydantic import BaseModel, Field

# --- What the model returns -------------------------------------------------
#
# The model refers to items by their 1-based position in the prompt's WARDROBE
# list, never by UUID. Two reasons: a position is a single token the model cannot
# plausibly typo into another valid item, and an out-of-range index is trivially
# detectable — whereas a hallucinated UUID would have to be looked up to be
# caught. The service maps positions back to ids and drops anything out of range,
# so a pick can only ever name an item that was actually retrieved.


class AnswerPick(BaseModel):
    index: int = Field(
        description="1-based position of the chosen item in the WARDROBE list."
    )
    reason: str = Field(
        description="One sentence on why this item answers the request."
    )


class AnswerDraft(BaseModel):
    """The structured-output schema handed to OpenAI."""

    answer: str = Field(
        description="A short, direct reply to the shopper, in the second person."
    )
    has_match: bool = Field(
        description=(
            "True only if the wardrobe genuinely contains what was asked for. "
            "False when offering the closest alternative instead."
        )
    )
    picks: list[AnswerPick] = Field(
        description="Items worth showing, best first. Empty if none are relevant."
    )


# --- What the API returns ---------------------------------------------------


class SearchAnswerItem(BaseModel):
    """One recommended item, resolved from a pick back to a real item.

    Deliberately not an `ItemRead`. This is what a result card needs — a picture,
    a label, and the sentence explaining why it is on screen — and nothing else.
    The full record stays one `GET /items/{item_id}` away.
    """

    item_id: UUID
    # Both come from the item, not the model: `title` is its stored analysis
    # title, `image_url` its first image presigned at read time. Either can be
    # null for a row that has images or analysis missing, which search excludes
    # anyway — so in practice both are populated.
    title: str | None
    image_url: str | None
    # Written by the model, about this item, in answer to this query.
    reason: str


class ItemSearchResponse(BaseModel):
    """What GET /items/search returns: a reply, and the items behind it."""

    answer: str
    # False means "nothing here is really what you asked for" — the answer then
    # offers the nearest thing rather than pretending it matched.
    has_match: bool
    # Only the items the model chose to show, best first. Empty when nothing
    # retrieved was worth showing; `answer` says why.
    items: list[SearchAnswerItem]

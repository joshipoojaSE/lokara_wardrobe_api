from typing import Protocol

from app.schemas.answer import AnswerDraft


class WardrobeAnswerer(Protocol):
    """Grounded answering seen from the service layer. Tests substitute a fake.

    Takes the shopper's question and a pre-rendered block of retrieved wardrobe
    items — the retrieval has already happened, so this never touches the
    database or the embedder. Raises `AnswerError` when the model cannot be
    reached or answers unusably.
    """

    async def answer(self, query: str, context: str) -> AnswerDraft: ...

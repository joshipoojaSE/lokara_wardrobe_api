from typing import Protocol


class ItemEmbedder(Protocol):
    """Text to vector, seen from the service layer. Tests substitute a fake.

    Returns a plain `list[float]` of exactly `EMBEDDING_DIMENSIONS` values so the
    service can hand it straight to the `Vector` column without conversion.
    Raises `EmbeddingError` when the model cannot be reached or answers unusably.
    """

    async def embed(self, text: str) -> list[float]: ...

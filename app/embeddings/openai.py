import logging

import openai

from app.core.exceptions import EmbeddingError
from app.models.analysis import EMBEDDING_DIMENSIONS

logger = logging.getLogger(__name__)


class OpenAIItemEmbedder:
    """Turns the rendered analysis text into a vector for the `embedding` column.

    The width is pinned to `EMBEDDING_DIMENSIONS` — the same constant the column
    is declared with — and asserted on the way out, because a mismatched vector
    fails at insert time with a Postgres error that says nothing about which
    model produced it.
    """

    def __init__(
        self,
        *,
        api_key: str | None,
        model: str,
        timeout_seconds: float = 30.0,
    ) -> None:
        self.model = model
        self._api_key = api_key or None
        self._timeout_seconds = timeout_seconds
        self._client: openai.AsyncOpenAI | None = None

    def _get_client(self) -> openai.AsyncOpenAI:
        """Built on first use, then reused — see `OpenAIItemAnalyzer._get_client`.

        The constructor raises when no key is configured; doing that at startup
        would turn a missing key into a 500 on item creation rather than a
        skipped embedding.
        """
        if self._client is None:
            try:
                # api_key=None lets the SDK fall back to OPENAI_API_KEY in the
                # environment.
                self._client = openai.AsyncOpenAI(
                    api_key=self._api_key, timeout=self._timeout_seconds
                )
            except openai.OpenAIError as exc:
                raise EmbeddingError(f"OpenAI client is not configured: {exc}") from exc
        return self._client

    async def embed(self, text: str) -> list[float]:
        if not text.strip():
            raise EmbeddingError("Cannot embed empty text.")

        try:
            response = await self._get_client().embeddings.create(
                model=self.model,
                input=text,
                dimensions=EMBEDDING_DIMENSIONS,
            )
        except EmbeddingError:
            raise
        except openai.OpenAIError as exc:
            raise EmbeddingError(f"Embedding request failed: {exc}") from exc

        if not response.data:
            raise EmbeddingError("Embedding response carried no vector.")

        vector = response.data[0].embedding
        if len(vector) != EMBEDDING_DIMENSIONS:
            raise EmbeddingError(
                f"{self.model} returned {len(vector)} dimensions; the column "
                f"holds {EMBEDDING_DIMENSIONS}."
            )

        usage = response.usage
        logger.info(
            "embedded analysis model=%s input_tokens=%s",
            self.model,
            getattr(usage, "prompt_tokens", "?"),
        )
        return list(vector)

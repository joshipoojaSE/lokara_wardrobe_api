import logging
from typing import Any

import openai
import pydantic

from app.answers.prompt import PROMPT_TEXT, QUERY_HEADING, WARDROBE_HEADING
from app.core.exceptions import AnswerError
from app.schemas.answer import AnswerDraft

logger = logging.getLogger(__name__)


class OpenAIWardrobeAnswerer:
    """Answers a wardrobe question from retrieved items with an OpenAI call.

    Mirrors `OpenAIItemAnalyzer`: the response shape is pinned by structured
    outputs — `AnswerDraft` goes to `responses.parse()` as a strict JSON schema —
    so the model cannot reply with prose or a markdown fence, and `output_parsed`
    comes back already validated.
    """

    def __init__(
        self,
        *,
        api_key: str | None,
        model: str,
        effort: str = "low",
        max_output_tokens: int = 4000,
        timeout_seconds: float = 90.0,
    ) -> None:
        self.model = model
        self.effort = effort
        self.max_output_tokens = max_output_tokens
        self._api_key = api_key or None
        self._timeout_seconds = timeout_seconds
        self._client: openai.AsyncOpenAI | None = None

    def _get_client(self) -> openai.AsyncOpenAI:
        """Built on first use, then reused — as in the analyzer, so a missing key
        surfaces as an answer failure rather than a startup crash."""
        if self._client is None:
            try:
                # api_key=None lets the SDK fall back to OPENAI_API_KEY in the
                # environment.
                self._client = openai.AsyncOpenAI(
                    api_key=self._api_key, timeout=self._timeout_seconds
                )
            except openai.OpenAIError as exc:
                raise AnswerError(f"OpenAI client is not configured: {exc}") from exc
        return self._client

    async def answer(self, query: str, context: str) -> AnswerDraft:
        # The wardrobe goes last: the request is what the rules above it apply
        # to, and the retrieved items are the data those rules constrain.
        prompt = (
            f"{PROMPT_TEXT}\n\n"
            f"{QUERY_HEADING}\n{query}\n\n"
            f"{WARDROBE_HEADING}\n{context}\n"
        )

        extra: dict[str, Any] = {}
        if self.effort:
            # Reasoning-model only; non-reasoning models reject it, so it is
            # switchable off with a blank ANSWER_EFFORT.
            extra["reasoning"] = {"effort": self.effort}

        try:
            response = await self._get_client().responses.parse(
                model=self.model,
                max_output_tokens=self.max_output_tokens,
                text_format=AnswerDraft,
                input=[{"role": "user", "content": prompt}],
                **extra,
            )
        except AnswerError:
            raise
        except openai.OpenAIError as exc:
            raise AnswerError(f"Answer request failed: {exc}") from exc
        except pydantic.ValidationError as exc:
            raise AnswerError(f"Answer returned an unusable shape: {exc}") from exc

        _raise_on_refusal(response)
        if response.status == "incomplete":
            reason = getattr(response.incomplete_details, "reason", "unknown")
            raise AnswerError(f"Answer stopped early: {reason}.")
        if response.output_parsed is None:
            raise AnswerError("Answer returned no structured output.")

        usage = response.usage
        logger.info(
            "answered query model=%s input_tokens=%s output_tokens=%s",
            self.model,
            getattr(usage, "input_tokens", "?"),
            getattr(usage, "output_tokens", "?"),
        )
        return response.output_parsed


def _raise_on_refusal(response: Any) -> None:
    """A declined request comes back 200 with a refusal block, not an exception."""
    for item in response.output:
        if item.type != "message":
            continue
        for block in item.content:
            if block.type == "refusal":
                raise AnswerError(f"Answer was declined: {block.refusal}")

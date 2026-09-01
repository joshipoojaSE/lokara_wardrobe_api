import base64
import logging
from collections.abc import Sequence
from typing import Any

import openai
import pydantic

from app.analysis.prompt import MULTI_IMAGE_NOTE, PROMPT_TEXT
from app.core.exceptions import AnalysisError
from app.schemas.analysis import ItemAnalysisResult
from app.storage.base import ImageUpload

logger = logging.getLogger(__name__)


class OpenAIItemAnalyzer:
    """Describes a garment with an OpenAI vision call.

    The response shape is pinned by structured outputs — `ItemAnalysisResult` is
    handed to `responses.parse()` as a strict JSON schema, so the model cannot
    answer with prose, a markdown fence, or a missing field, and `output_parsed`
    comes back already validated.
    """

    def __init__(
        self,
        *,
        api_key: str | None,
        model: str,
        effort: str = "medium",
        max_output_tokens: int = 16000,
        timeout_seconds: float = 180.0,
        max_images: int = 4,
    ) -> None:
        self.model = model
        self.effort = effort
        self.max_output_tokens = max_output_tokens
        self.max_images = max_images
        self._api_key = api_key or None
        self._timeout_seconds = timeout_seconds
        self._client: openai.AsyncOpenAI | None = None

    def _get_client(self) -> openai.AsyncOpenAI:
        """Built on first use, then reused.

        The constructor raises when no key is configured, and doing that at
        startup would turn a missing key into a 500 on item creation instead of
        an analysis failure recorded on the item.
        """
        if self._client is None:
            try:
                # api_key=None lets the SDK fall back to OPENAI_API_KEY in the
                # environment.
                self._client = openai.AsyncOpenAI(
                    api_key=self._api_key, timeout=self._timeout_seconds
                )
            except openai.OpenAIError as exc:
                raise AnalysisError(f"OpenAI client is not configured: {exc}") from exc
        return self._client

    async def analyze(self, images: Sequence[ImageUpload]) -> ItemAnalysisResult:
        if not images:
            raise AnalysisError("Cannot analyze an item with no images.")

        # Several photos of one garment sharpen the read; past a handful they only
        # add cost, so send the first few and say they are the same item.
        selected = list(images)[: self.max_images]
        content: list[dict[str, Any]] = [
            {
                "type": "input_image",
                "image_url": (
                    f"data:{image.content_type};base64,"
                    f"{base64.standard_b64encode(image.data).decode('ascii')}"
                ),
            }
            for image in selected
        ]
        prompt = PROMPT_TEXT
        if len(selected) > 1:
            prompt = f"{PROMPT_TEXT}\n{MULTI_IMAGE_NOTE}"
        content.append({"type": "input_text", "text": prompt})

        extra: dict[str, Any] = {}
        if self.effort:
            # Reasoning-model only; non-reasoning models reject it, so it is
            # switchable off with an empty ANALYSIS_EFFORT.
            extra["reasoning"] = {"effort": self.effort}

        try:
            response = await self._get_client().responses.parse(
                model=self.model,
                max_output_tokens=self.max_output_tokens,
                text_format=ItemAnalysisResult,
                input=[{"role": "user", "content": content}],
                **extra,
            )
        except AnalysisError:
            raise
        except openai.OpenAIError as exc:
            raise AnalysisError(f"Vision analysis request failed: {exc}") from exc
        except pydantic.ValidationError as exc:
            raise AnalysisError(
                f"Vision analysis returned an unusable shape: {exc}"
            ) from exc

        _raise_on_refusal(response)
        if response.status == "incomplete":
            reason = getattr(response.incomplete_details, "reason", "unknown")
            raise AnalysisError(f"Vision analysis stopped early: {reason}.")
        if response.output_parsed is None:
            raise AnalysisError("Vision analysis returned no structured output.")
        usage = response.usage
        logger.info(
            "analyzed item images=%d input_tokens=%s output_tokens=%s",
            len(selected),
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
                raise AnalysisError(f"Vision analysis was declined: {block.refusal}")

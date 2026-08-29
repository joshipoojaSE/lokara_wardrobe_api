from collections.abc import Sequence
from typing import Protocol

from app.schemas.analysis import ItemAnalysisResult
from app.storage.base import ImageUpload


class ItemAnalyzer(Protocol):
    """Vision analysis seen from the service layer. Tests substitute a fake.

    Takes the item's images as `ImageUpload` — the same carrier the storage layer
    uses — so a freshly uploaded file and one read back from S3 look identical.
    Raises `AnalysisError` when the model cannot be reached or answers unusably.
    """

    async def analyze(self, images: Sequence[ImageUpload]) -> ItemAnalysisResult: ...

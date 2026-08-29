from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class ImageUpload:
    """One inbound file, already read off the wire. Carries no HTTP types."""

    filename: str
    content_type: str
    data: bytes

    @property
    def size_bytes(self) -> int:
        return len(self.data)


class ImageStorage(Protocol):
    """Object storage seen from the service layer. Tests substitute a fake."""

    async def upload(self, *, key: str, upload: ImageUpload) -> None: ...

    async def download(self, key: str) -> ImageUpload: ...

    async def delete(self, keys: Sequence[str]) -> None: ...

    def url_for(self, key: str) -> str: ...

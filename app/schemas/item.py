from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ItemBase(BaseModel):
    """The describable fields of an item.

    All optional: an item is created from images alone and described afterwards
    via PATCH, so every field starts out null.
    """

    model_config = ConfigDict(from_attributes=True)

    name: str | None = Field(default=None, min_length=1, max_length=120)
    category: str | None = Field(default=None, min_length=1, max_length=50)
    color: str | None = Field(default=None, max_length=40)
    brand: str | None = Field(default=None, max_length=80)
    size: str | None = Field(default=None, max_length=20)
    notes: str | None = None


class ItemUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    category: str | None = Field(default=None, min_length=1, max_length=50)
    color: str | None = Field(default=None, max_length=40)
    brand: str | None = Field(default=None, max_length=80)
    size: str | None = Field(default=None, max_length=20)
    notes: str | None = None


class ItemImageRead(BaseModel):
    """`url` is presigned at read time, so it is not stored and it expires."""

    id: UUID
    url: str
    content_type: str
    size_bytes: int
    created_at: datetime


class ItemRead(ItemBase):
    id: UUID
    created_at: datetime
    updated_at: datetime
    images: list[ItemImageRead] = []

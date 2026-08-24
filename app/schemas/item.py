from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ItemBase(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    category: str = Field(min_length=1, max_length=50)
    color: str | None = Field(default=None, max_length=40)
    brand: str | None = Field(default=None, max_length=80)
    size: str | None = Field(default=None, max_length=20)
    notes: str | None = None


class ItemCreate(ItemBase):
    pass


class ItemUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    category: str | None = Field(default=None, min_length=1, max_length=50)
    color: str | None = Field(default=None, max_length=40)
    brand: str | None = Field(default=None, max_length=80)
    size: str | None = Field(default=None, max_length=20)
    notes: str | None = None


class ItemRead(ItemBase):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    created_at: datetime
    updated_at: datetime

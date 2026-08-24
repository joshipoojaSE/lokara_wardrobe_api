from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDMixin


class WardrobeItem(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "wardrobe_items"

    name: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    category: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    color: Mapped[str | None] = mapped_column(String(40))
    brand: Mapped[str | None] = mapped_column(String(80))
    size: Mapped[str | None] = mapped_column(String(20))
    notes: Mapped[str | None] = mapped_column(Text)

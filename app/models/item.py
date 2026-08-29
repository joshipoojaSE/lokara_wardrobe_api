from typing import TYPE_CHECKING

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.analysis import ItemAnalysis
    from app.models.image import ItemImage


class WardrobeItem(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "wardrobe_items"

    # Nullable: an item is created from images alone and described later.
    name: Mapped[str | None] = mapped_column(String(120), index=True)
    category: Mapped[str | None] = mapped_column(String(50), index=True)
    color: Mapped[str | None] = mapped_column(String(40))
    brand: Mapped[str | None] = mapped_column(String(80))
    size: Mapped[str | None] = mapped_column(String(20))
    notes: Mapped[str | None] = mapped_column(Text)

    # Lifecycle of the background vision analysis: pending -> ready | failed.
    analysis_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", server_default="pending"
    )
    analysis_error: Mapped[str | None] = mapped_column(Text)

    # selectin, not lazy: async attribute access cannot emit an implicit SELECT.
    images: Mapped[list["ItemImage"]] = relationship(
        back_populates="item",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="ItemImage.position",
    )

    analysis: Mapped["ItemAnalysis | None"] = relationship(
        back_populates="item",
        cascade="all, delete-orphan",
        lazy="selectin",
        uselist=False,
    )

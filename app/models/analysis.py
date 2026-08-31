import uuid
from typing import TYPE_CHECKING, Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import ForeignKey, Integer, JSON, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.item import WardrobeItem

# Portable like `sa.Uuid` in app/db/base.py: plain JSON keeps the model usable on
# SQLite, the variant still renders jsonb on Postgres so the arrays are indexable.
JsonList = JSON().with_variant(JSONB, "postgresql")

# Width of the `embedding` column. Lives here rather than in settings because
# changing it needs a migration — a config knob could silently disagree with the
# column. `text-embedding-3-small` emits 1536 natively, and 1536 stays under
# pgvector's 2000-dimension ceiling for hnsw/ivfflat indexes.
EMBEDDING_DIMENSIONS = 1536


class ItemAnalysis(UUIDMixin, TimestampMixin, Base):
    """Vision-model output for one item. One row per item, replaced on re-analysis.

    Scalar fields get their own column so the Mix & Match algorithm can filter on
    them; the four list fields are JSON.
    """

    __tablename__ = "item_analysis"

    item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("wardrobe_items.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )

    title: Mapped[str] = mapped_column(String(200), nullable=False)
    type: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    category: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    brand_guess: Mapped[str | None] = mapped_column(String(120))
    colors_hex: Mapped[list[Any]] = mapped_column(JsonList, nullable=False)
    color_family: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    material: Mapped[str] = mapped_column(String(80), nullable=False)
    fabric_weight: Mapped[str] = mapped_column(String(20), nullable=False)
    fit: Mapped[str] = mapped_column(String(60), nullable=False)
    cut: Mapped[str] = mapped_column(String(20), nullable=False)
    silhouette_match: Mapped[str] = mapped_column(String(120), nullable=False)
    pattern: Mapped[str] = mapped_column(String(80), nullable=False)
    print_position: Mapped[str] = mapped_column(String(20), nullable=False)
    sleeve_length: Mapped[str] = mapped_column(String(40), nullable=False)
    neckline: Mapped[str] = mapped_column(String(20), nullable=False)
    length: Mapped[str] = mapped_column(String(20), nullable=False)
    style_vibe: Mapped[str] = mapped_column(String(80), nullable=False)
    occasion: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    formality_score: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    wardrobe_role: Mapped[str] = mapped_column(String(20), nullable=False)
    visual_weight: Mapped[str] = mapped_column(String(20), nullable=False)
    season: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    temperature_range: Mapped[str] = mapped_column(String(40), nullable=False)
    layering_suggestion: Mapped[str] = mapped_column(String(20), nullable=False)
    separability: Mapped[str] = mapped_column(String(20), nullable=False)
    harmonizing_colors_hex: Mapped[list[Any]] = mapped_column(JsonList, nullable=False)
    harmonizing_families: Mapped[list[Any]] = mapped_column(JsonList, nullable=False)
    pairing_suggestions: Mapped[list[Any]] = mapped_column(JsonList, nullable=False)
    tags: Mapped[list[Any]] = mapped_column(JsonList, nullable=False)

    # The analysis rendered as text and embedded, for similarity search. Unlike
    # `sa.Uuid` and `JsonList` above this one is Postgres-only — pgvector has no
    # SQLite equivalent. Nullable: an embedding failure must not cost the
    # analysis, so a stored row may legitimately have no vector yet.
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(EMBEDDING_DIMENSIONS), nullable=True
    )

    item: Mapped["WardrobeItem"] = relationship(back_populates="analysis")

"""item name and category nullable

Revision ID: e5a2c9d17f30
Revises: b41c7d3e59a2
Create Date: 2026-08-27 15:04:11.902517

"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = 'e5a2c9d17f30'
down_revision: str | None = 'b41c7d3e59a2'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        'wardrobe_items', 'name',
        existing_type=sa.String(length=120),
        nullable=True,
    )
    op.alter_column(
        'wardrobe_items', 'category',
        existing_type=sa.String(length=50),
        nullable=True,
    )


def downgrade() -> None:
    # Rows created image-first carry NULLs that NOT NULL would reject, so they
    # are backfilled before the constraint goes back on.
    op.execute(
        "UPDATE wardrobe_items SET name = 'Untitled' WHERE name IS NULL"
    )
    op.execute(
        "UPDATE wardrobe_items SET category = 'uncategorized' WHERE category IS NULL"
    )
    op.alter_column(
        'wardrobe_items', 'category',
        existing_type=sa.String(length=50),
        nullable=False,
    )
    op.alter_column(
        'wardrobe_items', 'name',
        existing_type=sa.String(length=120),
        nullable=False,
    )

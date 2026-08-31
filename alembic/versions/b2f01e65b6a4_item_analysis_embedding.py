"""item analysis embedding

Revision ID: b2f01e65b6a4
Revises: 30e40908e342
Create Date: 2026-08-31 12:52:22.273534

"""
from collections.abc import Sequence

from alembic import op
import pgvector.sqlalchemy
import sqlalchemy as sa


revision: str = 'b2f01e65b6a4'
down_revision: str | None = '30e40908e342'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Autogenerate emits neither of the statements around the column: the
    # extension must exist before `vector` is a type, and it does not see the
    # hnsw index because the model does not declare one.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.add_column(
        'item_analysis',
        sa.Column('embedding', pgvector.sqlalchemy.Vector(1536), nullable=True),
    )
    # Cosine distance (`<=>`): OpenAI embeddings arrive normalized, so cosine and
    # inner product rank identically and cosine is the conventional read.
    op.create_index(
        'ix_item_analysis_embedding',
        'item_analysis',
        ['embedding'],
        postgresql_using='hnsw',
        postgresql_ops={'embedding': 'vector_cosine_ops'},
        postgresql_with={'m': '16', 'ef_construction': '64'},
    )


def downgrade() -> None:
    op.drop_index('ix_item_analysis_embedding', table_name='item_analysis')
    op.drop_column('item_analysis', 'embedding')
    # The extension is left in place: dropping it would take any other vector
    # column in the database with it.

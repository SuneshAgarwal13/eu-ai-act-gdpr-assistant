"""add full-text search column for hybrid retrieval

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-18

"""

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    # Generated, so every existing and future row gets one with no ingest change.
    op.execute(
        "ALTER TABLE chunks ADD COLUMN IF NOT EXISTS tsv tsvector "
        "GENERATED ALWAYS AS (to_tsvector('english', content)) STORED"
    )
    op.execute("CREATE INDEX IF NOT EXISTS chunks_tsv_gin_idx ON chunks USING gin (tsv)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS chunks_tsv_gin_idx")
    op.execute("ALTER TABLE chunks DROP COLUMN IF EXISTS tsv")

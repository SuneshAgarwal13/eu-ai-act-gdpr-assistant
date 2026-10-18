"""weight provision titles and status-note headings in the full-text index

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-18

"""

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | None = None
depends_on: str | None = None

# The first line of a binding chunk is its provision's title ("Article 11 — Technical
# documentation", "Annex IV — Technical documentation referred to in Article 11(1)"),
# the most precise signal of what it governs. Weighted A, it counts ten times a body
# match in ts_rank_cd. Status notes get the same treatment for their section heading
# ("New application dates for high-risk AI systems"); without it, "when do high-risk
# obligations apply?" ranked Article 26's title above the note that answers it. Guidance
# is left out: its first line repeats the whole document's title, which would lift every
# paragraph of it at once.
_TSV = """
    CASE WHEN metadata->>'authority' IN ('binding', 'status')
         THEN setweight(to_tsvector('english', split_part(content, E'\\n', 1)), 'A')
         ELSE ''::tsvector
    END || to_tsvector('english', content)
"""


def upgrade() -> None:
    op.execute("DROP INDEX IF EXISTS chunks_tsv_gin_idx")
    op.execute("ALTER TABLE chunks DROP COLUMN IF EXISTS tsv")
    op.execute(f"ALTER TABLE chunks ADD COLUMN tsv tsvector GENERATED ALWAYS AS ({_TSV}) STORED")
    op.execute("CREATE INDEX chunks_tsv_gin_idx ON chunks USING gin (tsv)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS chunks_tsv_gin_idx")
    op.execute("ALTER TABLE chunks DROP COLUMN IF EXISTS tsv")
    op.execute(
        "ALTER TABLE chunks ADD COLUMN tsv tsvector "
        "GENERATED ALWAYS AS (to_tsvector('english', content)) STORED"
    )
    op.execute("CREATE INDEX chunks_tsv_gin_idx ON chunks USING gin (tsv)")

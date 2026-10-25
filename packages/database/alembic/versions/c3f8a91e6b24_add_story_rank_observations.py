"""Record story ranking observations without changing story or cluster rows.

Revision ID: c3f8a91e6b24
Revises: c4d91ab27e05

Adds ranking_run.source and ranking_run.failed_story_id, and the story_rank
table. Existing ranking_run rows are cluster observations: source is a
non-null constant default, so PostgreSQL 11+ stores it in the catalog and
does not rewrite the table. story_rank is new and empty.

lock_timeout is the Alembic env default (30s, ALEMBIC_LOCK_TIMEOUT). These
statements only need a brief lock; the deploy stops scraper and clusterer
before migrations. statement_timeout stays unset. Downgrade drops only the
objects this revision adds.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "c3f8a91e6b24"
down_revision = "c4d91ab27e05"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ranking_run",
        sa.Column("source", sa.String(), nullable=False, server_default=sa.text("'cluster'")),
    )
    op.create_check_constraint(
        "ck_ranking_run_source",
        "ranking_run",
        "source IN ('cluster', 'story')",
    )
    op.add_column("ranking_run", sa.Column("failed_story_id", sa.Integer(), nullable=True))
    op.create_table(
        "story_rank",
        sa.Column("ranking_run_id", sa.Integer(), nullable=False),
        sa.Column("story_id", sa.Integer(), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("ranked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("rank_version", sa.String(), nullable=False),
        sa.Column("rank_components", postgresql.JSONB(), nullable=False),
        sa.Column("rank_category", sa.String(), nullable=True),
        sa.CheckConstraint("score BETWEEN 0 AND 1", name="ck_story_rank_score"),
        sa.ForeignKeyConstraint(
            ["ranking_run_id"], ["ranking_run.id"],
            name="story_rank_ranking_run_id_fkey", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["story_id"], ["story.id"],
            name="story_rank_story_id_fkey", ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("ranking_run_id", "story_id", name="story_rank_pkey"),
    )
    op.create_index("ix_story_rank_story_id", "story_rank", ["story_id"])


def downgrade() -> None:
    op.drop_index("ix_story_rank_story_id", table_name="story_rank")
    op.drop_table("story_rank")
    op.drop_column("ranking_run", "failed_story_id")
    op.drop_constraint("ck_ranking_run_source", "ranking_run", type_="check")
    op.drop_column("ranking_run", "source")

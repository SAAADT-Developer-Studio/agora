"""Persist cluster ranking and previously discarded ranking inputs.

Revision ID: e73b90a4f612
Revises: d4a8c21f7e6b
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "e73b90a4f612"
down_revision = "d4a8c21f7e6b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # No backfill: historical observation times and membership strengths are unknown.
    op.add_column("article", sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("article_cluster", sa.Column("membership_confidence", sa.Float(), nullable=True))
    op.create_check_constraint(
        "ck_article_cluster_membership_confidence", "article_cluster",
        "membership_confidence BETWEEN 0 AND 1",
    )
    for column in (
        sa.Column("rank_score", sa.Float(), nullable=True),
        sa.Column("ranked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rank_components", postgresql.JSONB(), nullable=True),
        sa.Column("rank_version", sa.String(), nullable=True),
        sa.Column("rank_config", postgresql.JSONB(), nullable=True),
        sa.Column("rank_category", sa.String(), nullable=True),
    ):
        op.add_column("cluster_v2", column)
    op.create_check_constraint("ck_cluster_v2_rank_score", "cluster_v2", "rank_score BETWEEN 0 AND 1")
    op.create_index("ix_cluster_v2_created_at_id", "cluster_v2", ["created_at", "id"])


def downgrade() -> None:
    op.drop_index("ix_cluster_v2_created_at_id", table_name="cluster_v2")
    op.drop_constraint("ck_cluster_v2_rank_score", "cluster_v2", type_="check")
    for name in ("rank_category", "rank_config", "rank_version", "rank_components", "ranked_at", "rank_score"):
        op.drop_column("cluster_v2", name)
    op.drop_constraint("ck_article_cluster_membership_confidence", "article_cluster", type_="check")
    op.drop_column("article_cluster", "membership_confidence")
    op.drop_column("article", "first_seen_at")

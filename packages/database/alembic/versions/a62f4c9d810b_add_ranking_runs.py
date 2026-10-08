"""Record ranking runs and link each cluster's latest result to its run.

Revision ID: a62f4c9d810b
Revises: f91a6d2c830e
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "a62f4c9d810b"
down_revision = "f91a6d2c830e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ranking_run",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_days", sa.Integer(), nullable=False),
        sa.Column("algorithm_version", sa.String(), nullable=False),
        sa.Column("config", postgresql.JSONB(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("scored_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("expired_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("skipped_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_cluster_id", sa.Integer(), nullable=True),
        sa.Column("error", sa.String(), nullable=True),
        sa.CheckConstraint(
            "status IN ('running', 'succeeded', 'failed', 'interrupted')",
            name="ck_ranking_run_status",
        ),
        sa.CheckConstraint("window_days > 0", name="ck_ranking_run_window_days"),
        sa.CheckConstraint(
            "scored_count >= 0 AND expired_count >= 0 AND skipped_count >= 0",
            name="ck_ranking_run_counts",
        ),
    )
    op.create_index("ix_ranking_run_started_at", "ranking_run", ["started_at"])
    op.add_column("cluster_v2", sa.Column("ranking_run_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_cluster_v2_ranking_run_id", "cluster_v2", "ranking_run",
        ["ranking_run_id"], ["id"], ondelete="SET NULL",
    )
    op.create_index("ix_cluster_v2_ranking_run_id", "cluster_v2", ["ranking_run_id"])


def downgrade() -> None:
    op.drop_index("ix_cluster_v2_ranking_run_id", table_name="cluster_v2")
    op.drop_constraint("fk_cluster_v2_ranking_run_id", "cluster_v2", type_="foreignkey")
    op.drop_column("cluster_v2", "ranking_run_id")
    op.drop_index("ix_ranking_run_started_at", table_name="ranking_run")
    op.drop_table("ranking_run")

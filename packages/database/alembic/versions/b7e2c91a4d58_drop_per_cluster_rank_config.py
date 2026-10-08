"""Drop the per-cluster copy of ranking configuration.

The effective configuration is stored once on ranking_run.config and referenced
from cluster_v2.ranking_run_id.

Revision ID: b7e2c91a4d58
Revises: a62f4c9d810b
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "b7e2c91a4d58"
down_revision = "a62f4c9d810b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("cluster_v2", "rank_config")


def downgrade() -> None:
    op.add_column("cluster_v2", sa.Column("rank_config", postgresql.JSONB(), nullable=True))

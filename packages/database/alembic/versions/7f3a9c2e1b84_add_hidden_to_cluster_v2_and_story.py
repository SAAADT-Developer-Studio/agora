"""add hidden to cluster_v2 and story

Revision ID: 7f3a9c2e1b84
Revises: e4b7c2a81d06

Operator flag on the two tables readers serve. Existing rows stay visible.
Postgres 17 stores a constant boolean default in the catalog, so this does
not rewrite cluster_v2 or story. Applied by `alembic upgrade head` on deploy.

lock_timeout is the Alembic env default (30s, ALEMBIC_LOCK_TIMEOUT).
statement_timeout stays unset.
"""

from alembic import op
import sqlalchemy as sa

revision = "7f3a9c2e1b84"
down_revision = "e4b7c2a81d06"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "cluster_v2",
        sa.Column(
            "hidden",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "story",
        sa.Column(
            "hidden",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("story", "hidden")
    op.drop_column("cluster_v2", "hidden")

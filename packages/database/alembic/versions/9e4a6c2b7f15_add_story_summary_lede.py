"""Add story_summary.lede.

Revision ID: 9e4a6c2b7f15
Revises: 7b2e4f9c1d08
"""

from alembic import op
import sqlalchemy as sa

revision = "9e4a6c2b7f15"
down_revision = "7b2e4f9c1d08"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("story_summary", sa.Column("lede", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("story_summary", "lede")

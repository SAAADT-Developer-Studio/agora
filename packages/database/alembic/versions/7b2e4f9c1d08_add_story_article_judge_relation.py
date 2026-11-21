"""Add story_article.judge_relation.

Revision ID: 7b2e4f9c1d08
Revises: c4d91ab27e05
"""

from alembic import op
import sqlalchemy as sa

revision = "7b2e4f9c1d08"
down_revision = "c4d91ab27e05"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("story_article", sa.Column("judge_relation", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("story_article", "judge_relation")

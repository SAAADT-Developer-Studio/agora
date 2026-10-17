"""Add story_summary: generated headline and bullets, one row per refresh.

Revision ID: d2f7a3c91e54
Revises: b7e2c91a4d58
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "d2f7a3c91e54"
down_revision = "b7e2c91a4d58"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "story_summary",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("story_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("bullets", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("lead_article_id", sa.Integer(), nullable=True),
        sa.Column("model", sa.String(), nullable=False),
        sa.Column("prompt_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["story_id"], ["story.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["lead_article_id"], ["article.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_story_summary_story_id_id", "story_summary", ["story_id", "id"])


def downgrade() -> None:
    op.drop_index("ix_story_summary_story_id_id", table_name="story_summary")
    op.drop_table("story_summary")

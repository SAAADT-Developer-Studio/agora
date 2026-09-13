"""add story tables

Revision ID: c8e4f1a92b70
Revises: d4a8c21f7e6b
Create Date: 2026-09-13 13:20:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c8e4f1a92b70"
down_revision: Union[str, Sequence[str], None] = "d4a8c21f7e6b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "story",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("last_article_published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_story_last_article_published_at",
        "story",
        ["last_article_published_at"],
    )
    op.create_table(
        "story_article",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("story_id", sa.Integer(), nullable=False),
        sa.Column("article_id", sa.Integer(), nullable=False),
        sa.Column("method", sa.String(), nullable=False),
        sa.Column("similarity", sa.Float(), nullable=True),
        sa.Column("nearest_article_id", sa.Integer(), nullable=True),
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["article_id"], ["article.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["nearest_article_id"], ["article.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["story_id"], ["story.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("article_id", name="uq_story_article_article_id"),
    )
    op.create_index("ix_story_article_story_id", "story_article", ["story_id"])


def downgrade() -> None:
    op.drop_index("ix_story_article_story_id", table_name="story_article")
    op.drop_table("story_article")
    op.drop_index("ix_story_last_article_published_at", table_name="story")
    op.drop_table("story")

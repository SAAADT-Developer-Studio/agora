"""Record whether a story title came from the first article or an LLM headline.

Revision ID: c4e8b1a70d23
Revises: b7e2c91a4d58
"""

from alembic import op
import sqlalchemy as sa

revision = "c4e8b1a70d23"
down_revision = "b7e2c91a4d58"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("story", sa.Column("title_source", sa.String(), nullable=True))
    op.add_column(
        "story", sa.Column("title_generated_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("story", sa.Column("title_lead_article_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_story_title_lead_article_id",
        "story",
        "article",
        ["title_lead_article_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_check_constraint(
        "ck_story_title_source",
        "story",
        "title_source IS NULL OR title_source IN ('article', 'generated')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_story_title_source", "story", type_="check")
    op.drop_constraint("fk_story_title_lead_article_id", "story", type_="foreignkey")
    op.drop_column("story", "title_lead_article_id")
    op.drop_column("story", "title_generated_at")
    op.drop_column("story", "title_source")

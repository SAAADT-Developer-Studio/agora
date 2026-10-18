"""Add story.merged_into_story_id and story_article.story_similarity.

Revision ID: 3c5e8b1f9a27
Revises: d2f7a3c91e54
"""

from alembic import op
import sqlalchemy as sa

revision = "3c5e8b1f9a27"
down_revision = "d2f7a3c91e54"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("story", sa.Column("merged_into_story_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "story_merged_into_story_id_fkey",
        "story",
        "story",
        ["merged_into_story_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.add_column("story_article", sa.Column("story_similarity", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("story_article", "story_similarity")
    op.drop_constraint("story_merged_into_story_id_fkey", "story", type_="foreignkey")
    op.drop_column("story", "merged_into_story_id")

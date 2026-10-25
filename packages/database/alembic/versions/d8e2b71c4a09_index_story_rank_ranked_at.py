"""Index story_rank.ranked_at so retention deletes are a range scan.

Revision ID: d8e2b71c4a09
Revises: c3f8a91e6b24

The ranking job deletes story_rank rows older than its retention window in
batches of ``ORDER BY ranked_at LIMIT``. Without this index that delete walks
story_rank_pkey. The index is the only change. Downgrade drops it and leaves
every row in place.

lock_timeout is the Alembic env default (30s, ALEMBIC_LOCK_TIMEOUT).
statement_timeout stays unset.
"""

from alembic import op

revision = "d8e2b71c4a09"
down_revision = "c3f8a91e6b24"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_story_rank_ranked_at", "story_rank", ["ranked_at"])


def downgrade() -> None:
    op.drop_index("ix_story_rank_ranked_at", table_name="story_rank")

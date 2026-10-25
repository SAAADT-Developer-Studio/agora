"""Index story_rank rows that still hold a component summary.

Revision ID: e4b7c2a81d06
Revises: d8e2b71c4a09

The slim used to visit every story_rank row for a story. Score-only history
is the bulk of that table. This partial index contains only rows whose
components are not the retained-score marker, ordered so the previous full
row is one probe. Downgrade drops the index and leaves every row in place.

lock_timeout is the Alembic env default (30s, ALEMBIC_LOCK_TIMEOUT).
statement_timeout stays unset.
"""

from alembic import op
import sqlalchemy as sa

revision = "e4b7c2a81d06"
down_revision = "d8e2b71c4a09"
branch_labels = None
depends_on = None

_UNRETAINED = "(rank_components ->> 'retained') IS DISTINCT FROM 'score'"


def upgrade() -> None:
    op.create_index(
        "ix_story_rank_unretained",
        "story_rank",
        ["story_id", "ranking_run_id"],
        postgresql_where=sa.text(_UNRETAINED),
    )


def downgrade() -> None:
    op.drop_index("ix_story_rank_unretained", table_name="story_rank")

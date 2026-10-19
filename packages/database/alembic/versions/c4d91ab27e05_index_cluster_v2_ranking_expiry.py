"""Index the clusters the ranking expiry sweep still has to visit.

Revision ID: c4d91ab27e05
Revises: 3c5e8b1f9a27

cluster_v2 is kept forever. The expiry sweep only updates rows that are not
already the expired sentinel, but ``ORDER BY id LIMIT`` was planned as a
primary-key walk that heap-fetched every older expired row first. This
partial index is that sentinel's complement, ordered by id, so a page stops
after the rows it can still return.

CREATE INDEX CONCURRENTLY cannot run inside Alembic's transaction, so the
build uses an autocommit block. Deploy stops scraper and clusterer first and
sets lock_timeout (default 30s): the build fails if it cannot take its brief
ShareUpdateExclusive lock, instead of waiting out the deploy. statement_timeout
is left unset, so the build itself is allowed to finish. A failed CONCURRENTLY
leaves an invalid index that the planner will not use and that IF NOT EXISTS
would not replace, so drop any leftover before creating it.
"""

from alembic import op
import sqlalchemy as sa

revision = "c4d91ab27e05"
down_revision = "3c5e8b1f9a27"
branch_labels = None
depends_on = None

# Same predicate as database.schema.CLUSTER_V2_NEEDS_RANKING_EXPIRY.
# Frozen here: applied migrations do not follow later edits to the model.
_NEEDS_RANKING_EXPIRY = (
    "(rank_score IS DISTINCT FROM 0 "
    "OR (rank_components ->> 'status') IS DISTINCT FROM 'expired')"
)
_INDEX = "ix_cluster_v2_needs_ranking_expiry"


def upgrade() -> None:
    with op.get_context().autocommit_block():
        # Clear an invalid index left by a killed CONCURRENTLY build.
        op.execute(sa.text(f"DROP INDEX CONCURRENTLY IF EXISTS {_INDEX}"))
        op.create_index(
            _INDEX,
            "cluster_v2",
            ["id"],
            unique=False,
            postgresql_where=sa.text(_NEEDS_RANKING_EXPIRY),
            postgresql_concurrently=True,
        )
        # Planner stats for the new partial index, before the next ranking run.
        op.execute(sa.text("ANALYZE cluster_v2"))


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(sa.text(f"DROP INDEX CONCURRENTLY IF EXISTS {_INDEX}"))

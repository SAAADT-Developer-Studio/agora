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

A dropped client does not always cancel the backend. PostgreSQL can keep
running CREATE INDEX CONCURRENTLY after the migration container is gone, and
DROP INDEX CONCURRENTLY on that same index waits for the build's
ShareUpdateExclusiveLock. Re-running this revision therefore refuses to drop
while another session is still building it, and leaves an already-valid index
in place instead of rebuilding it.
"""

from collections.abc import Mapping, Sequence
import logging

from alembic import op
import sqlalchemy as sa

log = logging.getLogger("alembic.runtime.migration")

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

# index_relid is set for CREATE INDEX CONCURRENTLY (it stays 0 for a
# non-concurrent build). The activity probe covers a backend whose query
# names this index before the progress row exists.
_PROGRESS_SQL = """
SELECT p.pid AS pid, p.command AS command, p.phase AS phase
FROM pg_stat_progress_create_index AS p
JOIN pg_class AS idx ON idx.oid = p.index_relid
WHERE idx.relname = :index_name
"""

_ACTIVITY_SQL = """
SELECT a.pid AS pid, a.state AS state, left(a.query, 240) AS query
FROM pg_stat_activity AS a
WHERE a.pid <> pg_backend_pid()
  AND a.datname = current_database()
  AND strpos(a.query, :index_name) > 0
  AND (
    strpos(upper(a.query), 'CREATE INDEX') > 0
    OR strpos(upper(a.query), 'DROP INDEX') > 0
    OR strpos(upper(a.query), 'REINDEX') > 0
  )
  AND a.state <> 'idle'
"""

_VALID_SQL = """
SELECT i.indisvalid
FROM pg_class AS c
JOIN pg_namespace AS n ON n.oid = c.relnamespace
JOIN pg_index AS i ON i.indexrelid = c.oid
WHERE n.nspname = 'public'
  AND c.relname = :index_name
"""

# DROP INDEX CONCURRENTLY waits for every transaction that has touched the
# table. This is who was holding that lock when the wait started.
_CLUSTER_V2_LOCKS_SQL = """
SELECT a.pid AS pid,
       a.xact_start AS xact_start,
       left(a.query, 200) AS query
FROM pg_locks AS l
JOIN pg_class AS c ON c.oid = l.relation
JOIN pg_stat_activity AS a ON a.pid = l.pid
WHERE c.relname = 'cluster_v2'
  AND l.pid <> pg_backend_pid()
"""


class IndexBuildInProgress(RuntimeError):
    """Another backend is still building ix_cluster_v2_needs_ranking_expiry."""


def _index_backends(connection) -> tuple[list[Mapping[str, object]], list[Mapping[str, object]]]:
    params = {"index_name": _INDEX}
    progress = list(connection.execute(sa.text(_PROGRESS_SQL), params).mappings().all())
    activity = list(connection.execute(sa.text(_ACTIVITY_SQL), params).mappings().all())
    return progress, activity


def _index_indisvalid(connection) -> bool | None:
    value = connection.execute(sa.text(_VALID_SQL), {"index_name": _INDEX}).scalar()
    if value is None:
        return None
    return bool(value)


def _refuse_if_index_build_in_progress(
    progress: Sequence[Mapping[str, object]],
    activity: Sequence[Mapping[str, object]],
) -> None:
    if not progress and not activity:
        return
    details: list[str] = []
    for row in progress:
        details.append(f"pid {row['pid']} {row['command']} phase {row['phase']}")
    for row in activity:
        details.append(f"pid {row['pid']} state {row['state']}: {row['query']}")
    raise IndexBuildInProgress(
        "ix_cluster_v2_needs_ranking_expiry is still being built or dropped by "
        "another PostgreSQL backend, likely the migration container left behind "
        "when an earlier deploy lost SSH. This run will not DROP INDEX "
        "CONCURRENTLY, because that waits behind the in-progress build. Let "
        "that backend finish, then run the migration again: a valid index is "
        "kept. To abandon the build, cancel that backend and re-run, which "
        "drops the invalid index and builds a new one. " + "; ".join(details)
    )


def ranking_expiry_index_action(
    progress: Sequence[Mapping[str, object]],
    activity: Sequence[Mapping[str, object]],
    indisvalid: bool | None,
) -> str:
    """Return ``ready`` when the index can be kept, or ``rebuild`` when it cannot.

    ``indisvalid`` is True, False, or None when this index is absent.
    ``IndexBuildInProgress`` means a drop would block on the other backend.
    """
    _refuse_if_index_build_in_progress(progress, activity)
    if indisvalid is True:
        return "ready"
    return "rebuild"


def ranking_expiry_index_steps(action: str) -> tuple[str, ...]:
    """DDL steps for one action. ``ready`` must not drop a valid index."""
    if action == "ready":
        return ("analyze",)
    if action == "rebuild":
        return ("drop", "create", "analyze")
    raise ValueError(f"unknown ranking expiry index action {action!r}")


def _log_cluster_v2_lock_holders() -> None:
    rows = op.execute(sa.text(_CLUSTER_V2_LOCKS_SQL)).mappings().all()
    if not rows:
        log.warning("cluster_v2 lock holders visible to this role: none")
        return
    for row in rows:
        log.warning(
            "cluster_v2 lock holder pid=%s xact_start=%s query=%s",
            row["pid"], row["xact_start"], row["query"],
        )


def upgrade() -> None:
    connection = op.get_bind()
    # Read-only probes stay in the migration transaction. CREATE INDEX
    # CONCURRENTLY below is the part that must not.
    action = ranking_expiry_index_action(
        *_index_backends(connection),
        _index_indisvalid(connection),
    )
    with op.get_context().autocommit_block():
        for step in ranking_expiry_index_steps(action):
            if step == "analyze":
                op.execute(sa.text("ANALYZE cluster_v2"))
            elif step == "drop":
                # Invalid or missing. Log who can block the drop, then drop.
                # A valid index never reaches this step.
                _log_cluster_v2_lock_holders()
                op.execute(sa.text(f"DROP INDEX CONCURRENTLY IF EXISTS {_INDEX}"))
            elif step == "create":
                op.create_index(
                    _INDEX,
                    "cluster_v2",
                    ["id"],
                    unique=False,
                    postgresql_where=sa.text(_NEEDS_RANKING_EXPIRY),
                    postgresql_concurrently=True,
                )
            else:
                raise ValueError(f"unknown ranking expiry index step {step!r}")


def downgrade() -> None:
    connection = op.get_bind()
    _refuse_if_index_build_in_progress(*_index_backends(connection))
    with op.get_context().autocommit_block():
        op.execute(sa.text(f"DROP INDEX CONCURRENTLY IF EXISTS {_INDEX}"))

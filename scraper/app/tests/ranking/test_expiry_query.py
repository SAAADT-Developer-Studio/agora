"""SQL shape of the ranking expiry page. No database connection."""

from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy.dialects import postgresql

from database import schema
from database.repositories import expired_ranking_statement

BEFORE = datetime(2026, 9, 18, tzinfo=timezone.utc)
PREDICATE = (
    "(rank_score IS DISTINCT FROM 0 "
    "OR (rank_components ->> 'status') IS DISTINCT FROM 'expired')"
)


def _sql(*, keep_run_id):
    statement = expired_ranking_statement(
        before=BEFORE, keep_run_id=keep_run_id, after_id=0, limit=100,
    )
    return str(statement.compile(dialect=postgresql.dialect()))


def test_expiry_predicate_is_literal_so_a_generic_plan_can_use_the_index():
    sql = _sql(keep_run_id=42)
    assert PREDICATE in sql
    # A bind here is planned as a primary-key walk once the statement is generic.
    assert "IS DISTINCT FROM %(" not in sql
    assert "->> %(" not in sql
    assert "cluster_v2.run_id != %(run_id_1)s" in sql
    assert (
        "(cluster_v2.created_at < %(created_at_1)s OR cluster_v2.rank_score IS NOT NULL)"
        in sql
    )
    assert "ORDER BY cluster_v2.id" in sql
    assert "LIMIT %(param_1)s" in sql


def test_expiry_without_a_kept_run_only_applies_the_age_cutoff():
    sql = _sql(keep_run_id=None)
    assert PREDICATE in sql
    assert "run_id !=" not in sql
    assert "rank_score IS NOT NULL" not in sql
    assert "cluster_v2.created_at < %(created_at_1)s" in sql


def test_expiry_limit_must_be_positive():
    with pytest.raises(ValueError):
        expired_ranking_statement(before=BEFORE, keep_run_id=1, limit=0)


def _expiry_index_migration():
    import importlib.util
    path = Path(schema.__file__).parent / (
        "alembic/versions/c4d91ab27e05_index_cluster_v2_ranking_expiry.py"
    )
    spec = importlib.util.spec_from_file_location("expiry_index_migration", path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


def test_partial_index_predicate_matches_the_sweep():
    migration = _expiry_index_migration()
    assert migration._NEEDS_RANKING_EXPIRY == schema.CLUSTER_V2_NEEDS_RANKING_EXPIRY
    assert schema.CLUSTER_V2_NEEDS_RANKING_EXPIRY in _sql(keep_run_id=42)


def test_in_progress_index_build_is_not_dropped():
    migration = _expiry_index_migration()
    progress = [{
        "pid": 42,
        "command": "CREATE INDEX CONCURRENTLY",
        "phase": "building index",
    }]
    with pytest.raises(
        migration.IndexBuildInProgress,
        match="will not DROP INDEX CONCURRENTLY",
    ) as exc:
        migration.ranking_expiry_index_action(progress, [], False)
    message = str(exc.value)
    assert "pid 42" in message
    assert "building index" in message
    assert "valid index is kept" in message


def test_active_create_index_session_is_not_dropped():
    migration = _expiry_index_migration()
    activity = [{
        "pid": 77,
        "state": "active",
        "query": "CREATE INDEX CONCURRENTLY ix_cluster_v2_needs_ranking_expiry ON cluster_v2 (id)",
    }]
    with pytest.raises(migration.IndexBuildInProgress, match="pid 77"):
        migration.ranking_expiry_index_action([], activity, None)


def test_valid_index_is_reused_and_a_dead_build_is_rebuilt():
    migration = _expiry_index_migration()
    assert migration.ranking_expiry_index_action([], [], True) == "ready"
    assert migration.ranking_expiry_index_action([], [], False) == "rebuild"
    assert migration.ranking_expiry_index_action([], [], None) == "rebuild"
    # upgrade() follows these steps, so a valid index never reaches DROP.
    assert migration.ranking_expiry_index_steps("ready") == ("analyze",)
    assert "drop" not in migration.ranking_expiry_index_steps("ready")
    assert migration.ranking_expiry_index_steps("rebuild") == ("drop", "create", "analyze")
    with pytest.raises(ValueError):
        migration.ranking_expiry_index_steps("other")


def test_drop_logs_cluster_v2_lock_holders():
    migration = _expiry_index_migration()
    sql = migration._CLUSTER_V2_LOCKS_SQL
    assert "a.pid AS pid" in sql
    assert "a.xact_start AS xact_start" in sql
    assert "left(a.query, 200) AS query" in sql
    assert "c.relname = 'cluster_v2'" in sql
    assert "l.pid <> pg_backend_pid()" in sql


def test_index_build_probe_names_this_index_and_ignores_idle_sessions():
    migration = _expiry_index_migration()
    assert "pg_stat_progress_create_index" in migration._PROGRESS_SQL
    assert "idx.relname = :index_name" in migration._PROGRESS_SQL
    assert "state <> 'idle'" in migration._ACTIVITY_SQL
    assert "CREATE INDEX" in migration._ACTIVITY_SQL
    assert "DROP INDEX" in migration._ACTIVITY_SQL
    assert "n.nspname = 'public'" in migration._VALID_SQL
    assert migration._INDEX == "ix_cluster_v2_needs_ranking_expiry"

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


def test_partial_index_predicate_matches_the_sweep():
    import importlib.util
    path = Path(schema.__file__).parent / (
        "alembic/versions/c4d91ab27e05_index_cluster_v2_ranking_expiry.py"
    )
    spec = importlib.util.spec_from_file_location("expiry_index_migration", path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    assert migration._NEEDS_RANKING_EXPIRY == schema.CLUSTER_V2_NEEDS_RANKING_EXPIRY
    assert schema.CLUSTER_V2_NEEDS_RANKING_EXPIRY in _sql(keep_run_id=42)

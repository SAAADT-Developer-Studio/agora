"""PostgreSQL integration checks; opt in with RANKING_TEST_DATABASE_URL.

Each test creates and removes its own temporary schema. It never uses DATABASE_URL
for connections, so ordinary test runs cannot write to the configured application DB.
"""

from datetime import datetime, timedelta, timezone
import importlib.util
import os
from pathlib import Path
import uuid

from alembic.migration import MigrationContext
from alembic.operations import Operations
import pytest
from sqlalchemy import create_engine, event, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from database import schema
from database.repositories import ClusterV2Repository
from database.schema import Base, ClusterRun, ClusterV2, RankingRun
from app.ranking.contracts import RankingConfig
from app.ranking.engine import ClusterRankingExplanation
from app.ranking.persistence import prepare_cluster
from app.tests.ranking.test_persistence import NOW, stored_cluster
from scripts.rank_clusters import RANKING_LOCK_KEY, handle_termination, main

pytestmark = pytest.mark.integration


@pytest.fixture
def db_engine():
    url = os.getenv("RANKING_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set RANKING_TEST_DATABASE_URL to a disposable PostgreSQL database")
    name = f"ranking_test_{uuid.uuid4().hex}"
    admin = create_engine(url)
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{name}"'))
    engine = create_engine(url, connect_args={"options": f"-csearch_path={name}"})
    try:
        Base.metadata.create_all(engine)
        yield engine
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{name}" CASCADE'))
        admin.dispose()


def seed(engine, clusters):
    with Session(engine) as session:
        run = ClusterRun(algo_version="test", params={}, is_production=True)
        run.id = 1
        run.created_at = NOW
        session.add(run)
        session.flush()
        session.add_all(clusters)
        session.commit()


def test_batch_window_and_cursor_keep_full_history_without_extra_queries(db_engine):
    cutoff = NOW - timedelta(days=30)
    seed(db_engine, [
        stored_cluster(cluster_id=1, created_at=cutoff - timedelta(microseconds=1)),
        stored_cluster(cluster_id=2, created_at=cutoff, published_at=NOW - timedelta(days=60)),
        stored_cluster(cluster_id=3, created_at=NOW),
        stored_cluster(cluster_id=4, created_at=NOW + timedelta(microseconds=1)),
    ])
    with Session(db_engine) as session:
        repo = ClusterV2Repository(session)
        first = repo.get_ranking_batch(since=cutoff, through=NOW, limit=1)
        assert [cluster.id for cluster in first] == [2]
        queries = []
        def record(*args):
            queries.append(args)
        event.listen(db_engine, "before_cursor_execute", record)
        try:
            snapshot = prepare_cluster(first[0], NOW, RankingConfig(version="test"))
        finally:
            event.remove(db_engine, "before_cursor_execute", record)
        assert not queries
        assert snapshot.articles[0].published_at == NOW - timedelta(days=60)
        second = repo.get_ranking_batch(since=cutoff, through=NOW, after_id=2, limit=1)
        assert [cluster.id for cluster in second] == [3]
        assert not repo.get_ranking_batch(since=cutoff, through=NOW, after_id=3, limit=1)


def test_command_dry_run_then_saves_all_pages_and_reruns(db_engine, monkeypatch):
    from database import unit_of_work
    monkeypatch.setattr(unit_of_work, "SessionMaker", sessionmaker(db_engine))
    now = datetime.now(timezone.utc)
    empty = stored_cluster(cluster_id=4, created_at=now - timedelta(hours=1))
    empty.memberships.clear()
    seed(db_engine, [
        stored_cluster(cluster_id=1, created_at=now - timedelta(days=31)),
        stored_cluster(cluster_id=2, created_at=now - timedelta(days=29)),
        stored_cluster(cluster_id=3, created_at=now - timedelta(hours=1)), empty,
    ])
    main(["--dry-run", "--batch-size", "1"])
    with Session(db_engine) as session:
        assert all(c.rank_score is None for c in session.scalars(select(ClusterV2)))
        assert not session.scalars(select(RankingRun)).all()
    main(["--batch-size", "1"])
    with Session(db_engine) as session:
        clusters = {c.id: c for c in session.scalars(select(ClusterV2))}
        assert clusters[1].rank_score == 0
        assert clusters[1].rank_components["status"] == "expired"
        assert "explanation" not in clusters[1].rank_components
        expired_at = clusters[1].ranked_at
        assert clusters[4].rank_score is None
        assert 0 <= clusters[2].rank_score <= 1
        assert 0 <= clusters[3].rank_score <= 1
        assert clusters[2].ranked_at == clusters[3].ranked_at
        old_evaluation = clusters[2].ranked_at
        assert clusters[2].rank_config["parameters"]["ranking"]["coverage_weight"] == 1
        assert "coverage_score" in clusters[2].rank_components
        assert clusters[2].rank_category == "sport"
        saved = ClusterRankingExplanation.model_validate(clusters[2].rank_components["explanation"])
        assert saved.result.score == clusters[2].rank_score
        assert saved.result.evaluated_at == clusters[2].ranked_at
        assert saved.article_contribution.articles[0].article_id == 2
        assert saved.publisher_authority.publishers[0].publisher_key == "publisher-2"
        assert saved.confidence.reports[0].membership_confidence == 0.8
        run = session.scalars(select(RankingRun)).one()
        first_run_id = run.id
        assert run.status == "succeeded"
        assert run.started_at == run.evaluated_at == clusters[2].ranked_at
        assert run.finished_at >= run.started_at
        assert (run.scored_count, run.expired_count, run.skipped_count) == (2, 1, 1)
        assert run.window_days == 30
        assert run.algorithm_version == clusters[2].rank_version
        assert run.config == clusters[2].rank_config
        assert all(clusters[id].ranking_run_id == run.id for id in (1, 2, 3))
        assert clusters[4].ranking_run_id is None
    main(["--batch-size", "2"])
    with Session(db_engine) as session:
        cluster = session.get(ClusterV2, 2)
        assert cluster.ranked_at > old_evaluation
        saved = ClusterRankingExplanation.model_validate(cluster.rank_components["explanation"])
        assert saved.result.evaluated_at == cluster.ranked_at
        assert saved.result.score == cluster.rank_score
        assert session.get(ClusterV2, 1).ranked_at == expired_at
        assert session.get(ClusterV2, 1).ranking_run_id == first_run_id
        runs = session.scalars(select(RankingRun).order_by(RankingRun.id)).all()
        assert len(runs) == 2
        assert runs[1].status == "succeeded"
        assert (runs[1].scored_count, runs[1].expired_count, runs[1].skipped_count) == (2, 0, 1)
        assert cluster.ranking_run_id == runs[1].id != first_run_id


@pytest.mark.parametrize("batch_size,committed", [(2, 0), (1, 1)])
@pytest.mark.parametrize("failure,status", [(ValueError, "failed"), (KeyboardInterrupt, "interrupted")])
def test_failure_rolls_back_current_batch(db_engine, monkeypatch, batch_size, committed, failure, status):
    from database import unit_of_work
    from app.ranking import persistence
    monkeypatch.setattr(unit_of_work, "SessionMaker", sessionmaker(db_engine))
    now = datetime.now(timezone.utc)
    seed(db_engine, [stored_cluster(cluster_id=id, created_at=now - timedelta(hours=1)) for id in (1, 2)])
    rank = persistence.rank_and_save_cluster
    def fail_second(cluster, *args, **kwargs):
        if cluster.id == 2:
            raise failure("bad input")
        return rank(cluster, *args, **kwargs)
    monkeypatch.setattr(persistence, "rank_and_save_cluster", fail_second)
    with pytest.raises(failure, match="bad input"):
        main(["--batch-size", str(batch_size)])
    with Session(db_engine) as session:
        assert sum(c.rank_score is not None for c in session.scalars(select(ClusterV2))) == committed
        run = session.scalars(select(RankingRun)).one()
        assert run.status == status
        assert run.finished_at >= run.started_at
        assert run.scored_count == committed
        assert run.expired_count == run.skipped_count == 0
        assert run.failed_cluster_id == 2
        assert run.error == f"{failure.__name__}: bad input"


def test_concurrent_invocation_does_not_write_and_released_lock_allows_rerun(db_engine, monkeypatch):
    from database import unit_of_work
    monkeypatch.setattr(unit_of_work, "SessionMaker", sessionmaker(db_engine))
    seed(db_engine, [stored_cluster(created_at=datetime.now(timezone.utc) - timedelta(hours=1))])
    with db_engine.begin() as connection:
        connection.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": RANKING_LOCK_KEY})
        main([])
        with Session(db_engine) as session:
            assert not session.scalars(select(RankingRun)).all()
            assert session.get(ClusterV2, 1).rank_score is None
    main([])
    with Session(db_engine) as session:
        assert session.scalars(select(RankingRun)).one().status == "succeeded"


def test_abandoned_run_recovered_only_by_real_run(db_engine, monkeypatch):
    from database import unit_of_work
    monkeypatch.setattr(unit_of_work, "SessionMaker", sessionmaker(db_engine))
    with Session(db_engine) as session:
        abandoned = RankingRun(evaluated_at=NOW, started_at=NOW, window_days=30,
                               algorithm_version="test", config={}, scored_count=10)
        session.add(abandoned)
        session.commit()
        abandoned_id = abandoned.id
    main(["--dry-run"])
    with Session(db_engine) as session:
        assert session.get(RankingRun, abandoned_id).status == "running"
    main([])
    with Session(db_engine) as session:
        abandoned = session.get(RankingRun, abandoned_id)
        assert abandoned.status == "interrupted"
        assert abandoned.scored_count == 10
        assert abandoned.finished_at > abandoned.started_at
        assert "Actual stop time unknown" in abandoned.error
        latest = session.scalars(select(RankingRun).order_by(RankingRun.id.desc())).first()
        assert latest.status == "succeeded"
        assert latest.scored_count == latest.expired_count == latest.skipped_count == 0


def test_lost_lock_connection_aborts_uncommitted_scores(db_engine, monkeypatch):
    from database import unit_of_work
    from app.ranking import persistence
    monkeypatch.setattr(unit_of_work, "SessionMaker", sessionmaker(db_engine))
    seed(db_engine, [stored_cluster(created_at=datetime.now(timezone.utc) - timedelta(hours=1))])
    rank = persistence.rank_and_save_cluster
    def lose_lock(cluster, *args, **kwargs):
        result = rank(cluster, *args, **kwargs)
        with db_engine.begin() as connection:
            assert connection.scalar(text(
                "SELECT pg_terminate_backend(pid) FROM pg_locks "
                "WHERE locktype = 'advisory' AND classid = 0 AND objid = :key AND granted"
            ), {"key": RANKING_LOCK_KEY})
        return result
    monkeypatch.setattr(persistence, "rank_and_save_cluster", lose_lock)
    with pytest.raises(DBAPIError):
        main([])
    with Session(db_engine) as session:
        run = session.scalars(select(RankingRun)).one()
        assert run.status == "failed"
        assert run.scored_count == 0
        assert session.get(ClusterV2, 1).rank_score is None


def test_expiry_boundary_and_zero_backfill_replace_stale_explanation(db_engine, monkeypatch):
    from database import unit_of_work
    from app.ranking import persistence
    from scripts import rank_clusters
    monkeypatch.setattr(unit_of_work, "SessionMaker", sessionmaker(db_engine))
    class Clock:
        @staticmethod
        def now(tz):
            return NOW
    monkeypatch.setattr(rank_clusters, "datetime", Clock)
    cutoff = NOW - timedelta(days=30)
    stale = stored_cluster(cluster_id=1, created_at=cutoff - timedelta(microseconds=1))
    stale.rank_score = 0.9
    stale.rank_components = {"explanation": {"result": {"score": 0.9}}}
    seed(db_engine, [stale, stored_cluster(cluster_id=2, created_at=cutoff),
                     stored_cluster(cluster_id=3, created_at=NOW + timedelta(microseconds=1))])
    ranked = []
    rank = persistence.rank_and_save_cluster
    def record(cluster, *args, **kwargs):
        ranked.append(cluster.id)
        return rank(cluster, *args, **kwargs)
    monkeypatch.setattr(persistence, "rank_and_save_cluster", record)
    main([])
    assert ranked == [2]  # Old history is zeroed without invoking the engine.
    with Session(db_engine) as session:
        old = session.get(ClusterV2, 1)
        assert old.rank_score == 0
        assert old.rank_components["status"] == "expired"
        assert old.rank_components["cutoff"] == cutoff.isoformat()
        assert "explanation" not in old.rank_components
        assert session.get(ClusterV2, 3).rank_score is None
    main(["--days", "31"])
    with Session(db_engine) as session:
        assert "explanation" in session.get(ClusterV2, 1).rank_components


def test_sigterm_handler_records_interrupted_run(db_engine, monkeypatch):
    import signal
    from database import unit_of_work
    from app.ranking import persistence
    monkeypatch.setattr(unit_of_work, "SessionMaker", sessionmaker(db_engine))
    seed(db_engine, [stored_cluster(created_at=datetime.now(timezone.utc) - timedelta(hours=1))])
    def terminate(*args, **kwargs):
        handle_termination(signal.SIGTERM, None)
    monkeypatch.setattr(persistence, "rank_and_save_cluster", terminate)
    with pytest.raises(SystemExit) as exc:
        main([])
    assert exc.value.code == 143
    with Session(db_engine) as session:
        run = session.scalars(select(RankingRun)).one()
        assert run.status == "interrupted"
        assert run.scored_count == 0
        assert session.get(ClusterV2, 1).rank_score is None


@pytest.mark.parametrize("table,column,value", [
    ("cluster_v2", "rank_score", -0.01), ("cluster_v2", "rank_score", 1.01),
    ("cluster_v2", "rank_score", float("nan")),
    ("article_cluster", "membership_confidence", -0.01),
    ("article_cluster", "membership_confidence", 1.01),
])
def test_database_enforces_unit_ranges(db_engine, table, column, value):
    seed(db_engine, [stored_cluster()])
    with pytest.raises(IntegrityError):
        with db_engine.begin() as connection:
            connection.execute(text(f"UPDATE {table} SET {column} = :value"), {"value": value})


def test_migration_upgrade_preserves_history_and_unknowns(db_engine):
    seed(db_engine, [stored_cluster()])
    path = Path(schema.__file__).parent / "alembic/versions/e73b90a4f612_persist_cluster_ranking.py"
    spec = importlib.util.spec_from_file_location("ranking_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with db_engine.begin() as connection:
        with Operations.context(MigrationContext.configure(connection)):
            migration.downgrade()
            assert connection.scalar(text("SELECT title FROM cluster_v2 WHERE id = 1")) == "Station"
            migration.upgrade()
    with Session(db_engine) as session:
        cluster = session.get(ClusterV2, 1)
        assert cluster.title == "Station"
        assert cluster.rank_score is None
        assert cluster.ranked_at is None
        assert cluster.memberships[0].membership_confidence is None
        assert cluster.memberships[0].article.first_seen_at is None


def test_ranking_run_migration_preserves_scores_and_links_latest_run(db_engine, monkeypatch):
    from database import unit_of_work
    monkeypatch.setattr(unit_of_work, "SessionMaker", sessionmaker(db_engine))
    cluster = stored_cluster(created_at=datetime.now(timezone.utc) - timedelta(hours=1))
    cluster.rank_score = 0.4
    seed(db_engine, [cluster])
    path = Path(schema.__file__).parent / "alembic/versions/a62f4c9d810b_add_ranking_runs.py"
    spec = importlib.util.spec_from_file_location("ranking_run_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with db_engine.begin() as connection:
        with Operations.context(MigrationContext.configure(connection)):
            migration.downgrade()
            assert connection.scalar(text("SELECT rank_score FROM cluster_v2 WHERE id = 1")) == 0.4
            migration.upgrade()
    main([])
    with Session(db_engine) as session:
        cluster = session.get(ClusterV2, 1)
        assert cluster.ranking_run_id is not None
        run = session.get(RankingRun, cluster.ranking_run_id)
        assert run.status == "succeeded"
        assert run.scored_count == 1
        session.delete(run)
        session.commit()
        assert session.get(ClusterV2, 1).ranking_run_id is None

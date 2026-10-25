"""PostgreSQL integration checks; opt in with RANKING_TEST_DATABASE_URL.

Each test creates and removes its own temporary schema. It never uses DATABASE_URL
for connections, so ordinary test runs cannot write to the configured application DB.
"""

from datetime import datetime, timedelta, timezone
import importlib.util
import os
from pathlib import Path
import re
import uuid

from alembic.migration import MigrationContext
from alembic.operations import Operations
import pytest
from sqlalchemy import and_, create_engine, event, or_, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from database import schema
from database.repositories import ClusterV2Repository, expired_ranking_statement
from database.schema import Base, ClusterRun, ClusterV2, RankingRun, Story, StoryRank, StorySummary
from app.ranking.contracts import RankingConfig
from app.ranking.persistence import SCORE_ONLY_COMPONENTS, prepare_cluster
from app.tests.ranking.test_persistence import NOW, stored_cluster, stored_story
from scripts.rank_clusters import RANKING_LOCK_KEY, handle_termination, main

pytestmark = pytest.mark.integration

# story_rank is the observation table and must stay writable. story, story_article,
# and story_summary must not: underscore is a word character, so a bare story
# name does not match story_rank.
_STORY_TABLE_WRITE = re.compile(
    r"\b(?:insert\s+into|update|delete\s+from)\s+\"?(?:story|story_article|story_summary)\"?(?!\w)",
    re.IGNORECASE,
)


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


def _add_run(session, run_id, created_at, *, production):
    run = ClusterRun(algo_version="test", params={}, is_production=production)
    run.id = run_id
    run.created_at = created_at
    session.add(run)
    return run


def _on_run(cluster, run_id):
    """Point a fixture cluster and its memberships at one clustering run."""
    cluster.run_id = run_id
    for membership in cluster.memberships:
        membership.run_id = run_id
    return cluster


def test_only_latest_production_run_is_selected(db_engine):
    older = _on_run(stored_cluster(cluster_id=1, created_at=NOW - timedelta(days=1)), 1)
    non_production = _on_run(stored_cluster(cluster_id=2, created_at=NOW), 2)
    latest_old_id = _on_run(stored_cluster(
        cluster_id=3, created_at=NOW - timedelta(days=2), published_at=NOW - timedelta(days=60),
    ), 3)
    latest_new_id = _on_run(stored_cluster(cluster_id=4, created_at=NOW), 3)
    newer_non_production = _on_run(stored_cluster(cluster_id=5, created_at=NOW + timedelta(hours=1)), 4)
    same_time_lower_id = _on_run(stored_cluster(cluster_id=6), 5)
    with Session(db_engine) as session:
        _add_run(session, 1, NOW - timedelta(days=3), production=True)
        _add_run(session, 2, NOW - timedelta(days=1), production=False)
        _add_run(session, 3, NOW, production=True)
        _add_run(session, 4, NOW + timedelta(hours=2), production=False)
        _add_run(session, 5, NOW, production=True)
        session.flush()
        session.add_all([
            older, non_production, latest_old_id, latest_new_id, newer_non_production, same_time_lower_id,
        ])
        session.commit()
        repo = ClusterV2Repository(session)
        from database.repositories import ClusterRunRepository
        assert ClusterRunRepository(session).get_latest_production_id() == 5
        # Run 5 is production and shares run 3's timestamp, so the higher id wins.
        # Re-home the assertion to the actual latest row and show run 3 is not selected.
        selected = repo.get_ranking_batch(run_id=5, limit=10)
        assert [cluster.id for cluster in selected] == [6]
        not_latest = repo.get_ranking_batch(run_id=3, limit=10)
        assert [cluster.id for cluster in not_latest] == [3, 4]
        first = repo.get_ranking_batch(run_id=3, limit=1)
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
        assert [cluster.id for cluster in repo.get_ranking_batch(run_id=3, after_id=3, limit=1)] == [4]
        assert not repo.get_ranking_batch(run_id=3, after_id=4, limit=1)


def _seed_stories(session, stories):
    for story in stories:
        session.add(story)
        session.flush()


def test_command_dry_run_then_saves_story_pages_and_reruns(db_engine, monkeypatch):
    from database import unit_of_work
    monkeypatch.setattr(unit_of_work, "SessionMaker", sessionmaker(db_engine))
    now = datetime.now(timezone.utc)
    untouched = stored_cluster(cluster_id=100, created_at=now)
    untouched.rank_score = 0.4
    untouched.rank_components = {"status": "scored"}
    fresh_published_at = now - timedelta(hours=1)
    fresh = stored_story(story_id=2, published_at=fresh_published_at)
    also_fresh = stored_story(story_id=3, published_at=now - timedelta(hours=2), article_id=30)
    blank = stored_story(story_id=4, published_at=now - timedelta(hours=1), article_id=40, title="")
    stale = stored_story(story_id=1, published_at=now - timedelta(days=15))
    merged = stored_story(
        story_id=5, published_at=now - timedelta(hours=1), article_id=50, merged_into_story_id=2,
    )
    with Session(db_engine) as session:
        _add_run(session, 1, now, production=True)
        session.flush()
        session.add(untouched)
        _seed_stories(session, [fresh, also_fresh, blank, stale, merged])
        session.commit()
    queries = []

    def record(conn, cursor, statement, parameters, context, executemany):
        queries.append(statement)

    main(["--dry-run", "--batch-size", "1"])
    with Session(db_engine) as session:
        assert session.get(ClusterV2, 100).rank_score == 0.4
        assert not session.scalars(select(RankingRun)).all()
        assert not session.scalars(select(StoryRank)).all()
        assert session.get(Story, 2).title == "Station"
    event.listen(db_engine, "before_cursor_execute", record)
    try:
        main(["--batch-size", "1"])
    finally:
        event.remove(db_engine, "before_cursor_execute", record)
    observed_sql = "\n".join(queries).lower()
    assert "cluster_v2" not in observed_sql
    assert "article_cluster" not in observed_sql
    assert "cluster_run" not in observed_sql
    assert _STORY_TABLE_WRITE.search("update story set title = 'x'")
    assert _STORY_TABLE_WRITE.search('delete from "story_article"')
    assert _STORY_TABLE_WRITE.search("insert into story_summary (id) values (1)")
    assert not _STORY_TABLE_WRITE.search("update story_rank set rank_components = '{}'")
    assert not _STORY_TABLE_WRITE.search("insert into story_rank (story_id) values (1)")
    assert _STORY_TABLE_WRITE.search(observed_sql) is None
    assert "story_rank" in observed_sql
    with Session(db_engine) as session:
        assert session.get(ClusterV2, 100).rank_score == 0.4
        assert session.get(ClusterV2, 100).ranking_run_id is None
        assert session.get(ClusterV2, 100).rank_components == {"status": "scored"}
        ranks = {row.story_id: row for row in session.scalars(select(StoryRank))}
        assert set(ranks) == {2, 3}
        assert ranks[2].ranked_at == ranks[3].ranked_at
        first_ranked_at = ranks[2].ranked_at
        assert 0 <= ranks[2].score <= 1
        assert "explanation" not in ranks[2].rank_components
        assert "coverage_score" in ranks[2].rank_components
        assert ranks[2].rank_category == "sport"
        assert session.get(Story, 1).merged_into_story_id is None
        assert session.get(Story, 5).merged_into_story_id == 2
        run = session.scalars(select(RankingRun)).one()
        first_run_id = run.id
        assert run.source == "story"
        assert run.status == "succeeded"
        assert run.started_at == run.evaluated_at == ranks[2].ranked_at
        assert run.finished_at >= run.started_at
        assert (run.scored_count, run.expired_count, run.skipped_count) == (2, 0, 1)
        assert run.window_days == 14
        assert run.failed_story_id is None
        assert run.algorithm_version == ranks[2].rank_version
        assert run.config["parameters"]["ranking"]["coverage_weight"] == 1
    main(["--batch-size", "2"])
    with Session(db_engine) as session:
        runs = session.scalars(select(RankingRun).order_by(RankingRun.id)).all()
        assert len(runs) == 2
        assert runs[1].source == "story"
        assert runs[1].status == "succeeded"
        assert (runs[1].scored_count, runs[1].expired_count, runs[1].skipped_count) == (2, 0, 1)
        history = session.scalars(select(StoryRank).where(StoryRank.story_id == 2)).all()
        assert len(history) == 2
        assert {row.ranking_run_id for row in history} == {first_run_id, runs[1].id}
        previous = next(row for row in history if row.ranking_run_id == first_run_id)
        current = next(row for row in history if row.ranking_run_id == runs[1].id)
        assert previous.ranked_at == first_ranked_at
        assert previous.rank_components == SCORE_ONLY_COMPONENTS
        assert 0 <= previous.score <= 1
        assert "coverage_score" in current.rank_components
        assert current.rank_components != SCORE_ONLY_COMPONENTS
        assert session.get(ClusterV2, 100).rank_score == 0.4
        assert session.get(Story, 2).last_article_published_at == fresh_published_at


@pytest.mark.parametrize("batch_size", [1, 2])
def test_broken_story_is_skipped_and_the_rest_score(db_engine, monkeypatch, batch_size):
    from database import unit_of_work
    from app.ranking import persistence
    monkeypatch.setattr(unit_of_work, "SessionMaker", sessionmaker(db_engine))
    now = datetime.now(timezone.utc)
    with Session(db_engine) as session:
        _seed_stories(session, [
            stored_story(story_id=story_id, published_at=now - timedelta(hours=1))
            for story_id in (1, 2)
        ])
        session.commit()
    rank = persistence.rank_and_save_story

    def fail_second(story, *args, **kwargs):
        if story.id == 2:
            raise ValueError("bad input")
        return rank(story, *args, **kwargs)

    monkeypatch.setattr(persistence, "rank_and_save_story", fail_second)
    main(["--batch-size", str(batch_size)])
    with Session(db_engine) as session:
        ranks = {row.story_id: row for row in session.scalars(select(StoryRank))}
        assert set(ranks) == {1}
        assert session.get(Story, 2).title == "Station"
        run = session.scalars(select(RankingRun)).one()
        assert run.status == "succeeded"
        assert run.source == "story"
        assert (run.scored_count, run.expired_count, run.skipped_count) == (1, 0, 1)
        assert run.failed_story_id is None
        assert run.failed_cluster_id is None
        assert run.error is None


@pytest.mark.parametrize("batch_size,committed", [(2, 0), (1, 1)])
def test_failure_rolls_back_current_story_batch(db_engine, monkeypatch, batch_size, committed):
    from database import unit_of_work
    from app.ranking import persistence
    monkeypatch.setattr(unit_of_work, "SessionMaker", sessionmaker(db_engine))
    now = datetime.now(timezone.utc)
    with Session(db_engine) as session:
        _seed_stories(session, [
            stored_story(story_id=story_id, published_at=now - timedelta(hours=1))
            for story_id in (1, 2)
        ])
        session.commit()
    rank = persistence.rank_and_save_story

    def fail_second(story, *args, **kwargs):
        if story.id == 2:
            raise KeyboardInterrupt("bad input")
        return rank(story, *args, **kwargs)

    monkeypatch.setattr(persistence, "rank_and_save_story", fail_second)
    with pytest.raises(KeyboardInterrupt, match="bad input"):
        main(["--batch-size", str(batch_size)])
    with Session(db_engine) as session:
        saved = session.scalars(select(StoryRank.story_id)).all()
        assert saved == ([1] if committed else [])
        run = session.scalars(select(RankingRun)).one()
        assert run.status == "interrupted"
        assert run.finished_at >= run.started_at
        assert run.scored_count == committed
        assert run.expired_count == run.skipped_count == 0
        assert run.failed_story_id == 2
        assert run.failed_cluster_id is None
        assert run.error == "KeyboardInterrupt: bad input"


def test_concurrent_invocation_does_not_write_and_released_lock_allows_rerun(db_engine, monkeypatch):
    from database import unit_of_work
    monkeypatch.setattr(unit_of_work, "SessionMaker", sessionmaker(db_engine))
    now = datetime.now(timezone.utc)
    cluster = stored_cluster(cluster_id=100, created_at=now)
    cluster.rank_score = 0.4
    with Session(db_engine) as session:
        _add_run(session, 1, now, production=True)
        session.flush()
        session.add(cluster)
        _seed_stories(session, [stored_story(published_at=now - timedelta(hours=1))])
        session.commit()
    with db_engine.begin() as connection:
        connection.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": RANKING_LOCK_KEY})
        main([])
        with Session(db_engine) as session:
            assert not session.scalars(select(RankingRun)).all()
            assert not session.scalars(select(StoryRank)).all()
            assert session.get(ClusterV2, 100).rank_score == 0.4
    main([])
    with Session(db_engine) as session:
        run = session.scalars(select(RankingRun)).one()
        assert run.status == "succeeded"
        assert run.source == "story"
        assert session.get(ClusterV2, 100).rank_score == 0.4
        assert session.scalars(select(StoryRank)).one().story_id == 1


def test_abandoned_run_recovered_only_by_real_run(db_engine, monkeypatch):
    from database import unit_of_work
    monkeypatch.setattr(unit_of_work, "SessionMaker", sessionmaker(db_engine))
    with Session(db_engine) as session:
        abandoned = RankingRun(evaluated_at=NOW, started_at=NOW, window_days=30,
                               algorithm_version="test", config={}, scored_count=10)
        session.add(abandoned)
        session.commit()
        abandoned_id = abandoned.id
        assert abandoned.source == "cluster"
    main(["--dry-run"])
    with Session(db_engine) as session:
        assert session.get(RankingRun, abandoned_id).status == "running"
        assert session.get(RankingRun, abandoned_id).source == "cluster"
    main([])
    with Session(db_engine) as session:
        abandoned = session.get(RankingRun, abandoned_id)
        assert abandoned.status == "interrupted"
        assert abandoned.source == "cluster"
        assert abandoned.scored_count == 10
        assert abandoned.finished_at > abandoned.started_at
        assert "Actual stop time unknown" in abandoned.error
        latest = session.scalars(select(RankingRun).order_by(RankingRun.id.desc())).first()
        assert latest.status == "succeeded"
        assert latest.source == "story"
        assert latest.window_days == 14
        assert latest.scored_count == latest.expired_count == latest.skipped_count == 0


def test_lost_lock_connection_aborts_uncommitted_scores(db_engine, monkeypatch):
    from database import unit_of_work
    from app.ranking import persistence
    monkeypatch.setattr(unit_of_work, "SessionMaker", sessionmaker(db_engine))
    now = datetime.now(timezone.utc)
    with Session(db_engine) as session:
        _seed_stories(session, [stored_story(published_at=now - timedelta(hours=1))])
        session.commit()
    rank = persistence.rank_and_save_story

    def lose_lock(story, *args, **kwargs):
        result = rank(story, *args, **kwargs)
        with db_engine.begin() as connection:
            assert connection.scalar(text(
                "SELECT pg_terminate_backend(pid) FROM pg_locks "
                "WHERE locktype = 'advisory' AND classid = 0 AND objid = :key AND granted"
            ), {"key": RANKING_LOCK_KEY})
        return result

    monkeypatch.setattr(persistence, "rank_and_save_story", lose_lock)
    with pytest.raises(DBAPIError):
        main([])
    with Session(db_engine) as session:
        run = session.scalars(select(RankingRun)).one()
        assert run.status == "failed"
        assert run.scored_count == 0
        assert not session.scalars(select(StoryRank)).all()
        assert session.get(Story, 1).title == "Station"


def test_story_window_excludes_old_merged_and_empty_stories(db_engine, monkeypatch):
    from database import unit_of_work
    from scripts import rank_clusters
    monkeypatch.setattr(unit_of_work, "SessionMaker", sessionmaker(db_engine))

    class Clock:
        @staticmethod
        def now(tz):
            return NOW

    monkeypatch.setattr(rank_clusters, "datetime", Clock)
    cutoff = NOW - timedelta(days=14)
    cluster = stored_cluster(cluster_id=9)
    cluster.rank_score = 0.9
    cluster.rank_components = {"explanation": {"kept": True}}
    old = stored_story(story_id=1, published_at=cutoff - timedelta(microseconds=1))
    boundary = stored_story(story_id=2, published_at=cutoff, article_id=20)
    fresh = stored_story(story_id=3, published_at=NOW, article_id=30)
    empty = stored_story(story_id=4, published_at=NOW, with_membership=False)
    merged = stored_story(
        story_id=5, published_at=NOW, article_id=50, merged_into_story_id=3,
    )
    with Session(db_engine) as session:
        _add_run(session, 1, NOW, production=True)
        session.flush()
        session.add(cluster)
        _seed_stories(session, [old, boundary, fresh, empty, merged])
        session.commit()
    main([])
    with Session(db_engine) as session:
        scored = set(session.scalars(select(StoryRank.story_id)))
        assert scored == {2, 3}
        run = session.scalars(select(RankingRun)).one()
        assert (run.scored_count, run.expired_count, run.skipped_count) == (2, 0, 0)
        assert session.get(ClusterV2, 9).rank_score == 0.9
        assert session.get(ClusterV2, 9).rank_components == {"explanation": {"kept": True}}
        assert session.get(Story, 5).merged_into_story_id == 3
    main(["--days", "15"])
    with Session(db_engine) as session:
        latest = session.scalars(select(RankingRun).order_by(RankingRun.id.desc())).first()
        assert latest.window_days == 15
        assert latest.scored_count == 3
        assert set(session.scalars(
            select(StoryRank.story_id).where(StoryRank.ranking_run_id == latest.id)
        )) == {1, 2, 3}
        assert session.get(ClusterV2, 9).rank_score == 0.9


def test_sigterm_handler_records_interrupted_run(db_engine, monkeypatch):
    import signal
    from database import unit_of_work
    from app.ranking import persistence
    monkeypatch.setattr(unit_of_work, "SessionMaker", sessionmaker(db_engine))
    now = datetime.now(timezone.utc)
    with Session(db_engine) as session:
        _seed_stories(session, [stored_story(published_at=now - timedelta(hours=1))])
        session.commit()

    def terminate(*args, **kwargs):
        handle_termination(signal.SIGTERM, None)

    monkeypatch.setattr(persistence, "rank_and_save_story", terminate)
    with pytest.raises(SystemExit) as exc:
        main([])
    assert exc.value.code == 143
    with Session(db_engine) as session:
        run = session.scalars(select(RankingRun)).one()
        assert run.status == "interrupted"
        assert run.scored_count == 0
        assert run.failed_story_id == 1
        assert not session.scalars(select(StoryRank)).all()


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
        # Current metadata no longer stores per-cluster rank_config. The historical
        # migration still drops that column, so put it back before exercising it.
        connection.execute(text("ALTER TABLE cluster_v2 ADD COLUMN IF NOT EXISTS rank_config jsonb"))
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
        # story_rank references ranking_run, which this historical migration drops.
        connection.execute(text("DROP TABLE IF EXISTS story_rank"))
        with Operations.context(MigrationContext.configure(connection)):
            migration.downgrade()
            assert connection.scalar(text("SELECT rank_score FROM cluster_v2 WHERE id = 1")) == 0.4
            migration.upgrade()
    with Session(db_engine) as session:
        cluster = session.get(ClusterV2, 1)
        assert cluster.rank_score == 0.4
        assert cluster.ranking_run_id is None


def _legacy_expired_ids(session, *, before, keep_run_id, after_id=0, limit=100):
    """Selection copied from before the expiry rewrite.

    The old filter was an OR of two AND branches, then AND-ed with the
    "not already expired" predicate and the id cursor. PostgreSQL's AND/OR
    precedence makes that the same rows as run_id exclusion AND (old OR scored)
    AND not-expired. This frozen copy is what the new statement has to match.
    """
    live_ranking = or_(
        ClusterV2.rank_score.is_distinct_from(0),
        ClusterV2.rank_components["status"].astext.is_distinct_from("expired"),
    )
    if keep_run_id is None:
        stale = ClusterV2.created_at < before
    else:
        other_run = ClusterV2.run_id != keep_run_id
        stale = or_(
            and_(other_run, ClusterV2.created_at < before),
            and_(other_run, ClusterV2.rank_score.is_not(None)),
        )
    return list(session.scalars(
        select(ClusterV2.id)
        .where(stale, live_ranking, ClusterV2.id > after_id)
        .order_by(ClusterV2.id)
        .limit(limit)
    ))


def _page_ids(session, *, before, keep_run_id, limit):
    repo = ClusterV2Repository(session)
    after_id = 0
    collected = []
    while True:
        new_page = [
            cluster.id for cluster in repo.get_expired_ranking_batch(
                before=before, keep_run_id=keep_run_id, after_id=after_id, limit=limit,
            )
        ]
        old_page = _legacy_expired_ids(
            session, before=before, keep_run_id=keep_run_id, after_id=after_id, limit=limit,
        )
        assert new_page == old_page
        if not new_page:
            return collected
        collected.extend(new_page)
        after_id = new_page[-1]


def test_expiry_pages_match_legacy_selection(db_engine):
    cutoff = datetime(2026, 9, 18, tzinfo=timezone.utc)
    cases = [
        # id, run_id, created_at, score, components
        (1, 1, cutoff - timedelta(days=1), None, None),
        (2, 1, cutoff - timedelta(days=1), 0.4, {"status": "scored"}),
        (3, 1, cutoff - timedelta(days=1), 0.0, {"status": "expired"}),
        (4, 1, cutoff - timedelta(days=1), 0.0, None),
        (5, 1, cutoff - timedelta(days=1), 0.0, {"status": "other"}),
        (6, 1, cutoff, None, None),
        (7, 1, cutoff, 0.2, {"status": "scored"}),
        (8, 1, cutoff + timedelta(days=1), None, None),
        (9, 1, cutoff + timedelta(days=1), 0.3, {"status": "scored"}),
        (10, 2, cutoff - timedelta(days=10), 0.9, {"status": "scored"}),
        (11, 2, cutoff + timedelta(days=1), 0.9, {"status": "scored"}),
        (12, 2, cutoff - timedelta(days=1), None, None),
        (13, 1, cutoff - timedelta(days=1), 0.0, {"status": "expired", "reason": "kept"}),
        (14, 3, cutoff + timedelta(days=1), 0.0, {"score": 0.0}),
        (15, 1, cutoff - timedelta(seconds=1), None, None),
    ]
    with Session(db_engine) as session:
        _add_run(session, 1, cutoff - timedelta(days=40), production=True)
        _add_run(session, 2, cutoff, production=True)
        _add_run(session, 3, cutoff + timedelta(days=1), production=False)
        session.flush()
        for cluster_id, run_id, created_at, score, components in cases:
            cluster = ClusterV2(title=f"cluster-{cluster_id}", slug=f"cluster-{cluster_id}", run_id=run_id)
            cluster.id = cluster_id
            cluster.created_at = created_at
            cluster.rank_score = score
            cluster.rank_components = components
            session.add(cluster)
        session.commit()
        # Kept run is 2. Exact cutoff with no score stays. Score 0 is still live
        # until status is the expired sentinel. Recent scored rows outside the
        # kept run are cleared; the same rows are kept when nothing is held.
        assert _page_ids(session, before=cutoff, keep_run_id=2, limit=4) == [
            1, 2, 4, 5, 7, 9, 14, 15,
        ]
        assert _page_ids(session, before=cutoff, keep_run_id=None, limit=3) == [
            1, 2, 4, 5, 10, 12, 15,
        ]
        assert _page_ids(session, before=cutoff, keep_run_id=2, limit=100) == [
            1, 2, 4, 5, 7, 9, 14, 15,
        ]


def test_expiry_generic_plan_uses_partial_index(db_engine):
    cutoff = datetime(2026, 9, 18, tzinfo=timezone.utc)
    with db_engine.begin() as connection:
        connection.execute(text(
            "INSERT INTO cluster_run (id, algo_version, params, is_production, created_at) "
            "VALUES (1, 'test', '{}', true, :old), (99, 'test', '{}', true, :new)"
        ), {"old": cutoff - timedelta(days=60), "new": cutoff + timedelta(days=20)})
        connection.execute(text(
            "INSERT INTO cluster_v2 (id, title, run_id, rank_score, rank_components, created_at) "
            "SELECT g, 'expired', 1, 0, '{\"status\":\"expired\"}'::jsonb, :created "
            "FROM generate_series(1, 100000) AS g"
        ), {"created": cutoff - timedelta(days=40)})
        connection.execute(text(
            "INSERT INTO cluster_v2 (id, title, run_id, rank_score, rank_components, created_at) "
            "SELECT 100000 + g, 'backlog', 1, NULL, NULL, :created "
            "FROM generate_series(1, 250) AS g"
        ), {"created": cutoff - timedelta(days=5)})
        connection.execute(text(
            "INSERT INTO cluster_v2 (id, title, run_id, rank_score, rank_components, created_at) "
            "SELECT 200000 + g, 'keep', 99, 0.5, '{\"status\":\"scored\"}'::jsonb, :created "
            "FROM generate_series(1, 20) AS g"
        ), {"created": cutoff + timedelta(days=1)})
        connection.execute(text("ANALYZE cluster_v2"))
    with Session(db_engine) as session:
        selected = _page_ids(session, before=cutoff, keep_run_id=99, limit=80)
        assert selected == list(range(100001, 100251))
        session.execute(text(
            "PREPARE expiry_probe (int, int, timestamptz, int) AS "
            "SELECT cluster_v2.id FROM cluster_v2 "
            "WHERE (rank_score IS DISTINCT FROM 0 "
            "OR (rank_components ->> 'status') IS DISTINCT FROM 'expired') "
            "AND cluster_v2.id > $1 AND cluster_v2.run_id != $2 "
            "AND (cluster_v2.created_at < $3 OR cluster_v2.rank_score IS NOT NULL) "
            "ORDER BY cluster_v2.id LIMIT $4"
        ))
        session.execute(text("SET plan_cache_mode = force_generic_plan"))
        plan = "\n".join(session.scalars(text(
            "EXPLAIN EXECUTE expiry_probe(0, 99, :cutoff, 100)"
        ), {"cutoff": cutoff}))
        assert "Index Scan using ix_cluster_v2_needs_ranking_expiry" in plan
        assert "cluster_v2_pkey" not in plan
        # The statement the job runs is the same predicate the probe prepared.
        compiled = str(expired_ranking_statement(
            before=cutoff, keep_run_id=99, after_id=0, limit=100,
        ).compile(dialect=session.bind.dialect))
        assert "rank_score IS DISTINCT FROM 0" in compiled
        assert "IS DISTINCT FROM %(" not in compiled


def test_story_page_failure_keeps_earlier_pages(db_engine, monkeypatch):
    from database import unit_of_work
    from app.ranking import stories
    monkeypatch.setattr(unit_of_work, "SessionMaker", sessionmaker(db_engine))
    now = datetime.now(timezone.utc)
    with Session(db_engine) as session:
        _seed_stories(session, [
            stored_story(story_id=1, published_at=now - timedelta(hours=2)),
            stored_story(story_id=2, published_at=now - timedelta(hours=1), article_id=20),
        ])
        session.commit()
    original = stories.load_story_batch
    calls = {"n": 0}

    def fail_second(session, **kwargs):
        calls["n"] += 1
        if calls["n"] == 2:
            raise TimeoutError("canceling statement due to statement timeout")
        return original(session, **kwargs)

    monkeypatch.setattr(stories, "load_story_batch", fail_second)
    with pytest.raises(TimeoutError):
        main(["--batch-size", "1"])
    with Session(db_engine) as session:
        saved = session.scalars(select(StoryRank.story_id)).all()
        assert saved == [1]
        assert session.get(Story, 2).title == "Station"
        run = session.scalars(select(RankingRun)).one()
        assert run.status == "failed"
        assert run.source == "story"
        assert run.scored_count == 1
        assert run.expired_count == 0
        assert run.failed_story_id is None


def test_story_rank_migration_is_reversible(db_engine):
    now = datetime.now(timezone.utc)
    with Session(db_engine) as session:
        historical = RankingRun(
            evaluated_at=now, started_at=now, window_days=30,
            algorithm_version="cluster-ranking-v1", config={"version": "initial-ranking-v1"},
            source="cluster",
        )
        session.add(historical)
        _seed_stories(session, [stored_story(published_at=now - timedelta(hours=1))])
        session.commit()
        run_id = historical.id
    path = Path(schema.__file__).parent / "alembic/versions/c3f8a91e6b24_add_story_rank_observations.py"
    spec = importlib.util.spec_from_file_location("story_rank_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with db_engine.begin() as connection:
        with Operations.context(MigrationContext.configure(connection)):
            migration.downgrade()
            assert connection.scalar(text("SELECT to_regclass('story_rank')")) is None
            columns = set(connection.scalars(text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = current_schema() AND table_name = 'ranking_run'"
            )))
            assert "source" not in columns
            assert "failed_story_id" not in columns
            assert connection.scalar(text("SELECT title FROM story WHERE id = 1")) == "Station"
            migration.upgrade()
        assert connection.scalar(text(
            "SELECT source FROM ranking_run WHERE id = :id"
        ), {"id": run_id}) == "cluster"
        connection.execute(text(
            "INSERT INTO story_rank (ranking_run_id, story_id, score, ranked_at, rank_version, rank_components) "
            "VALUES (:run_id, 1, 0.5, :at, 'cluster-ranking-v1', '{}'::jsonb)"
        ), {"run_id": run_id, "at": now})
    with pytest.raises(IntegrityError):
        with db_engine.begin() as connection:
            connection.execute(text(
                "UPDATE story_rank SET score = 1.2 WHERE story_id = 1"
            ))
    with Session(db_engine) as session:
        assert session.get(Story, 1).title == "Station"
        assert session.get(Story, 1).merged_into_story_id is None
        row = session.get(StoryRank, (run_id, 1))
        assert row.score == 0.5


def test_ranked_at_index_migration_keeps_rows(db_engine):
    now = datetime.now(timezone.utc)
    with Session(db_engine) as session:
        run = RankingRun(
            evaluated_at=now, started_at=now, window_days=14,
            algorithm_version="cluster-ranking-v1", config={}, source="story", status="succeeded",
        )
        session.add(run)
        _seed_stories(session, [stored_story(published_at=now - timedelta(hours=1))])
        session.flush()
        session.add(StoryRank(
            ranking_run_id=run.id, story_id=1, score=0.5, ranked_at=now,
            rank_version="v", rank_components={"coverage_score": 0.5},
        ))
        session.commit()
        run_id = run.id
    path = Path(schema.__file__).parent / "alembic/versions/d8e2b71c4a09_index_story_rank_ranked_at.py"
    spec = importlib.util.spec_from_file_location("story_rank_ranked_at_index", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with db_engine.begin() as connection:
        with Operations.context(MigrationContext.configure(connection)):
            assert connection.scalar(text("SELECT to_regclass('ix_story_rank_ranked_at')")) is not None
            migration.downgrade()
            assert connection.scalar(text("SELECT to_regclass('ix_story_rank_ranked_at')")) is None
            assert connection.scalar(text("SELECT score FROM story_rank WHERE story_id = 1")) == 0.5
            assert connection.scalar(text("SELECT title FROM story WHERE id = 1")) == "Station"
            migration.upgrade()
            assert connection.scalar(text("SELECT to_regclass('ix_story_rank_ranked_at')")) is not None
    with Session(db_engine) as session:
        assert session.get(StoryRank, (run_id, 1)).score == 0.5
        assert session.get(Story, 1).title == "Station"


def test_retention_deletes_old_story_observations_only(db_engine, monkeypatch):
    from database import unit_of_work
    from scripts import rank_clusters
    monkeypatch.setattr(unit_of_work, "SessionMaker", sessionmaker(db_engine))
    monkeypatch.setattr(rank_clusters, "STORY_RANK_RETENTION_BATCH", 1)
    now = datetime.now(timezone.utc)
    old_at = now - timedelta(days=20)
    recent_at = now - timedelta(days=1)
    cluster = stored_cluster(cluster_id=100, created_at=now)
    cluster.rank_score = 0.9
    cluster.rank_components = {"status": "scored"}
    with Session(db_engine) as session:
        _add_run(session, 1, now, production=True)
        session.flush()
        session.add(cluster)
        _seed_stories(session, [
            stored_story(story_id=1, published_at=old_at),
            stored_story(story_id=2, published_at=old_at, article_id=20),
            stored_story(story_id=3, published_at=recent_at, article_id=30),
        ])
        session.add(StorySummary(
            story_id=1, title="Kept summary",
            bullets=[{"text": "point", "article_ids": [1]}],
            lead_article_id=1, model="test", prompt_version=1,
        ))
        cluster_observation = RankingRun(
            evaluated_at=old_at, started_at=old_at, finished_at=old_at, window_days=30,
            algorithm_version="cluster-ranking-v1", config={}, status="succeeded", source="cluster",
        )
        old_run = RankingRun(
            evaluated_at=old_at, started_at=old_at, finished_at=old_at, window_days=14,
            algorithm_version="cluster-ranking-v1", config={}, status="succeeded", source="story",
        )
        recent_run = RankingRun(
            evaluated_at=recent_at, started_at=recent_at, finished_at=recent_at, window_days=14,
            algorithm_version="cluster-ranking-v1", config={}, status="succeeded", source="story",
        )
        still_running = RankingRun(
            evaluated_at=recent_at, started_at=recent_at, window_days=14,
            algorithm_version="cluster-ranking-v1", config={}, status="running", source="story",
        )
        session.add_all([cluster_observation, old_run, recent_run, still_running])
        session.flush()
        session.add_all([
            StoryRank(
                ranking_run_id=old_run.id, story_id=1, score=0.4, ranked_at=old_at,
                rank_version="v", rank_components={"coverage_score": 0.4},
            ),
            StoryRank(
                ranking_run_id=old_run.id, story_id=2, score=0.5,
                ranked_at=old_at + timedelta(seconds=1),
                rank_version="v", rank_components={"coverage_score": 0.5},
            ),
            StoryRank(
                ranking_run_id=recent_run.id, story_id=3, score=0.6, ranked_at=recent_at,
                rank_version="v", rank_components={"coverage_score": 0.6},
            ),
        ])
        session.commit()
        ids = {
            "cluster": cluster_observation.id,
            "old": old_run.id,
            "recent": recent_run.id,
            "running": still_running.id,
        }
    main(["--dry-run"])
    with Session(db_engine) as session:
        assert session.get(RankingRun, ids["old"]).status == "succeeded"
        assert session.get(StoryRank, (ids["old"], 1)).score == 0.4
        assert session.get(StoryRank, (ids["old"], 2)).score == 0.5
        assert len(session.scalars(select(RankingRun)).all()) == 4
    main([])
    with Session(db_engine) as session:
        assert session.get(RankingRun, ids["cluster"]).source == "cluster"
        assert session.get(RankingRun, ids["cluster"]).status == "succeeded"
        assert session.get(RankingRun, ids["old"]) is None
        assert session.get(StoryRank, (ids["old"], 1)) is None
        assert session.get(StoryRank, (ids["old"], 2)) is None
        kept = session.get(StoryRank, (ids["recent"], 3))
        assert kept.score == 0.6
        assert kept.ranked_at == recent_at
        assert kept.rank_components == SCORE_ONLY_COMPONENTS
        recovered = session.get(RankingRun, ids["running"])
        assert recovered.status == "interrupted"
        assert recovered.source == "story"
        latest = session.scalars(select(RankingRun).order_by(RankingRun.id.desc())).first()
        assert latest.source == "story"
        assert latest.status == "succeeded"
        assert latest.expired_count == 2
        assert latest.scored_count == 1
        fresh = session.scalars(select(StoryRank).where(StoryRank.ranking_run_id == latest.id)).one()
        assert fresh.story_id == 3
        assert "coverage_score" in fresh.rank_components
        assert session.get(ClusterV2, 100).rank_score == 0.9
        assert session.get(ClusterV2, 100).rank_components == {"status": "scored"}
        assert session.get(Story, 1).title == "Station"
        assert session.get(Story, 1).last_article_published_at == old_at
        assert session.get(StorySummary, 1).title == "Kept summary"
        assert set(session.scalars(select(Story.id))) == {1, 2, 3}


def _explain(session, statement) -> str:
    compiled = statement.compile(
        dialect=session.bind.dialect, compile_kwargs={"literal_binds": True},
    )
    return "\n".join(session.scalars(text("EXPLAIN " + str(compiled))))


def test_story_page_uses_publication_index(db_engine):
    from app.ranking.stories import load_story_batch, story_ranking_statement
    since = datetime.now(timezone.utc) - timedelta(days=14)
    old = since - timedelta(days=40)
    recent = since + timedelta(days=1)
    with db_engine.begin() as connection:
        connection.execute(text(
            "INSERT INTO news_provider (key, name, url, rank) "
            "VALUES ('p', 'P', 'https://p.test', 0)"
        ))
        connection.execute(text(
            "INSERT INTO story (id, title, last_article_published_at, created_at) "
            "SELECT g, 'old', :old, :old FROM generate_series(1, 20000) AS g"
        ), {"old": old})
        connection.execute(text(
            "INSERT INTO story (id, title, last_article_published_at, created_at) "
            "SELECT 20000 + g, 'new', :recent, :recent FROM generate_series(1, 40) AS g"
        ), {"recent": recent})
        connection.execute(text(
            "INSERT INTO story (id, title, last_article_published_at, created_at, merged_into_story_id) "
            "VALUES (20041, 'merged', :recent, :recent, 20001), "
            "(20042, 'empty', :recent, :recent, NULL)"
        ), {"recent": recent})
        connection.execute(text(
            "INSERT INTO article (id, url, title, published_at, embedding, news_provider_key) "
            "SELECT g, 'https://p.test/' || g, 't', :at, ARRAY[1.0]::double precision[], 'p' "
            "FROM generate_series(1, 20041) AS g"
        ), {"at": recent})
        connection.execute(text(
            "INSERT INTO story_article (story_id, article_id, method, assigned_at) "
            "SELECT g, g, 'cosine', :at FROM generate_series(1, 20041) AS g"
        ), {"at": recent})
        connection.execute(text("ANALYZE story"))
        connection.execute(text("ANALYZE story_article"))
    with Session(db_engine) as session:
        plan = _explain(session, story_ranking_statement(since=since, limit=10))
        assert "ix_story_last_article_published_at" in plan, plan
        assert "story_pkey" not in plan, plan
        collected = []
        cursor_at = None
        cursor_id = 0
        while True:
            page = load_story_batch(
                session, since=since, after_published_at=cursor_at, after_id=cursor_id, limit=7,
            )
            if not page:
                break
            collected.extend(story.id for story in page)
            cursor_at = page[-1].last_article_published_at
            cursor_id = page[-1].id
        assert collected == list(range(20001, 20041))
        paged = _explain(session, story_ranking_statement(
            since=since, after_published_at=cursor_at, after_id=20001, limit=10,
        ))
        assert "ix_story_last_article_published_at" in paged, paged
        assert "story_pkey" not in paged, paged

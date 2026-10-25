"""Story preparation and an observation ranking run. No database required."""

from contextlib import contextmanager
from datetime import timedelta
import logging
from math import nan
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql

from app.ranking.contracts import RankingConfig
from app.ranking.job import score_story
from app.ranking.persistence import (
    SCORE_ONLY_COMPONENTS, membership_confidence_from_story_similarity, prepare_story,
    rank_and_save_story, resolve_ranking_config,
)
from app.ranking.stories import story_ranking_statement
from app.tests.ranking.test_persistence import NOW, stored_story
from database.schema import RankingRun, StoryRank


def test_prepare_story_uses_articles_not_story_birth_or_nearest_article_similarity():
    story = stored_story(published_at=NOW - timedelta(days=3), story_similarity=0.88)
    story.created_at = NOW
    story.memberships[0].similarity = 0.2
    snapshot = prepare_story(story, NOW, RankingConfig(version="test"))
    article = snapshot.articles[0]
    assert snapshot.cluster_id == story.id
    assert snapshot.category == "sport"
    assert snapshot.created_at == NOW - timedelta(days=3)
    assert article.cluster_membership_confidence == 0.88
    assert article.publisher_authority_score == 1
    assert article.llm_rank == 8
    assert article.first_seen_at is None
    assert story.created_at == NOW
    assert story.memberships[0].similarity == 0.2


@pytest.mark.parametrize("raw,expected", [
    (None, None),
    (0, 0.0),
    (0.7, 0.7),
    (1, 1.0),
    (1 + 1e-9, 1.0),
    (-1e-9, 0.0),
    (-0.4, None),
    (1.2, None),
    (nan, None),
    (float("inf"), None),
    (True, None),
])
def test_story_similarity_maps_into_unit_interval_or_unknown(raw, expected):
    assert membership_confidence_from_story_similarity(raw, article_id=4) == expected


def test_prepare_story_does_not_change_story_or_article_fields():
    story = stored_story()
    article = story.memberships[0].article
    article.llm_rank = 0
    before = (
        story.title, story.last_article_published_at, story.merged_into_story_id,
        article.title, article.llm_rank, list(article.embedding),
        story.memberships[0].story_similarity,
    )
    assert prepare_story(story, NOW, RankingConfig(version="test")).articles[0].llm_rank is None
    assert before == (
        story.title, story.last_article_published_at, story.merged_into_story_id,
        article.title, article.llm_rank, list(article.embedding),
        story.memberships[0].story_similarity,
    )


def test_merged_story_is_refused_and_empty_story_is_not_a_rankable_cluster():
    merged = stored_story(story_id=2, merged_into_story_id=1)
    with pytest.raises(ValueError, match="merged"):
        prepare_story(merged, NOW, RankingConfig(version="test"))
    empty = stored_story(with_membership=False)
    with pytest.raises(ValidationError):
        prepare_story(empty, NOW, RankingConfig(version="test"))
    assert score_story(merged, NOW, RankingConfig(version="test"), ranking_run_id=1) == "skipped"
    assert score_story(empty, NOW, RankingConfig(version="test"), ranking_run_id=1) == "skipped"


def test_save_inserts_story_rank_and_leaves_the_story_unchanged(monkeypatch):
    story = stored_story()
    article = story.memberships[0].article
    before = (story.title, story.merged_into_story_id, article.title, article.llm_rank)
    added = []
    updates = []

    class Session:
        def add(self, obj):
            added.append(obj)

        def execute(self, statement, params=None):
            updates.append(statement)

    monkeypatch.setattr("app.ranking.persistence.object_session", lambda obj: Session())
    config = resolve_ranking_config(RankingConfig(version="initial-ranking-v1"))
    explanation = rank_and_save_story(story, NOW, config, ranking_run_id=7)
    assert len(added) == 1
    assert len(updates) == 1
    assert updates[0].table.name == "story_rank"
    bound = next(iter(updates[0]._values.values()))
    assert (bound.value if hasattr(bound, "value") else bound) == SCORE_ONLY_COMPONENTS
    row = added[0]
    assert isinstance(row, StoryRank)
    assert (row.ranking_run_id, row.story_id) == (7, story.id)
    assert row.score == explanation.result.score
    assert 0 < row.score <= 1
    assert row.rank_category == "sport"
    assert row.rank_version == explanation.algorithm_version
    assert "coverage_score" in row.rank_components
    assert "explanation" not in row.rank_components
    assert before == (story.title, story.merged_into_story_id, article.title, article.llm_rank)
    assert not hasattr(story, "rank_score")


def test_dry_run_records_nothing_on_the_story(monkeypatch):
    story = stored_story()

    def fail(obj):
        raise AssertionError("dry-run touched a session")

    monkeypatch.setattr("app.ranking.persistence.object_session", fail)
    config = resolve_ranking_config(RankingConfig(version="initial-ranking-v1"))
    explanation = rank_and_save_story(story, NOW, config, dry_run=True)
    assert 0 < explanation.result.score <= 1
    assert not hasattr(story, "rank_score")


def test_story_batch_query_reads_stories_only():
    statement = story_ranking_statement(since=NOW - timedelta(days=14), after_id=0, limit=25)
    sql = str(statement.compile(dialect=postgresql.dialect())).lower()
    assert "cluster_v2" not in sql
    assert "article_cluster" not in sql
    assert "cluster_run" not in sql
    assert "last_article_published_at" in sql
    assert "merged_into_story_id is null" in sql
    assert "story_article" in sql
    assert "order by story.last_article_published_at, story.id" in sql
    assert "story.id >" not in sql
    paged = story_ranking_statement(
        since=NOW - timedelta(days=14), after_published_at=NOW, after_id=4, limit=25,
    )
    paged_sql = str(paged.compile(dialect=postgresql.dialect())).lower()
    assert "(story.last_article_published_at, story.id) >" in paged_sql


class _Session:
    def __init__(self, lock=True, story_rank_relation="story_rank"):
        self.added = []
        self.sql = []
        self.lock = lock
        self.story_rank_relation = story_rank_relation

    def scalar(self, statement, params=None):
        sql = str(statement)
        self.sql.append(sql)
        if "pg_try_advisory_xact_lock" in sql:
            return self.lock
        if "to_regclass" in sql:
            return self.story_rank_relation
        raise AssertionError(sql)

    def execute(self, statement, params=None):
        sql = str(statement)
        self.sql.append(sql)
        lowered = sql.lower()
        for table in ("cluster_v2", "article_cluster", "cluster_run"):
            assert table not in lowered, sql
        table = getattr(statement, "table", None)
        values = getattr(statement, "_values", None)
        if getattr(table, "name", None) != "ranking_run" or not isinstance(values, dict):
            return SimpleNamespace(rowcount=0)
        applied = {}
        for key, bind in values.items():
            name = getattr(key, "key", None) or str(key)
            applied[name] = bind.value if hasattr(bind, "value") else bind
        for obj in self.added:
            if isinstance(obj, RankingRun):
                for name, value in applied.items():
                    setattr(obj, name, value)
        return SimpleNamespace(rowcount=0)

    def add(self, obj):
        self.added.append(obj)

    def flush(self):
        for obj in self.added:
            if isinstance(obj, RankingRun) and not getattr(obj, "id", None):
                obj.id = 1


def _patch_run(monkeypatch, session, pages):
    from scripts import rank_clusters

    calls = []

    @contextmanager
    def ranking_session():
        yield SimpleNamespace(session=session)

    def load_story_batch(db_session, *, since, after_published_at, after_id, limit):
        assert db_session is session
        calls.append((since, after_published_at, after_id, limit))
        return pages.pop(0)

    monkeypatch.setattr(rank_clusters, "ranking_session", ranking_session)
    monkeypatch.setattr("app.ranking.stories.load_story_batch", load_story_batch)
    monkeypatch.setattr("app.ranking.persistence.object_session", lambda obj: session)
    return rank_clusters, calls


def test_ranking_run_scores_stories_without_reading_clusters(monkeypatch, caplog):
    good = stored_story(story_id=1, story_similarity=0.91)
    unknown = stored_story(story_id=2, story_similarity=None, article_id=20)
    empty = stored_story(story_id=3, with_membership=False)
    merged = stored_story(story_id=4, merged_into_story_id=1, article_id=40)
    broken = stored_story(story_id=5, article_id=50, title="")
    session = _Session()
    rank_clusters, calls = _patch_run(monkeypatch, session, [[good, unknown, empty, merged, broken], []])
    with caplog.at_level(logging.INFO):
        rank_clusters.main([])
    assert "Finished run 1: 2 scored, 0 expired, 3 skipped." in caplog.text
    runs = [obj for obj in session.added if isinstance(obj, RankingRun)]
    rows = [obj for obj in session.added if isinstance(obj, StoryRank)]
    assert len(runs) == 1
    run = runs[0]
    assert run.source == "story"
    assert run.status == "succeeded"
    assert run.window_days == 14
    assert (run.scored_count, run.expired_count, run.skipped_count) == (2, 0, 3)
    assert run.failed_story_id is None
    assert {row.story_id for row in rows} == {1, 2}
    assert all(0 < row.score <= 1 for row in rows)
    assert all(row.ranking_run_id == run.id for row in rows)
    assert unknown.memberships[0].story_similarity is None
    assert rows[[row.story_id for row in rows].index(2)].rank_components["coverage_score"] >= 0
    assert calls[0][1] is None
    assert calls[0][2] == 0
    assert calls[1][1] == broken.last_article_published_at
    assert calls[1][2] == broken.id
    window = calls[0][0]
    assert window == run.evaluated_at - timedelta(days=14)
    joined = "\n".join(session.sql).lower()
    assert "cluster_v2" not in joined
    assert "article_cluster" not in joined
    assert "cluster_run" not in joined
    assert good.title == "Station"
    assert not hasattr(good, "rank_score")


def test_dry_run_and_busy_lock_write_nothing(monkeypatch):
    story = stored_story()
    session = _Session()
    rank_clusters, calls = _patch_run(monkeypatch, session, [[story], []])
    rank_clusters.main(["--dry-run"])
    assert session.added == []
    assert calls and not hasattr(story, "rank_score")
    session = _Session(lock=False)
    rank_clusters, calls = _patch_run(monkeypatch, session, [[story]])
    rank_clusters.main([])
    assert calls == []
    assert session.added == []


def test_missing_story_rank_skips_without_writing(monkeypatch, caplog):
    story = stored_story()
    session = _Session(story_rank_relation=None)
    rank_clusters, calls = _patch_run(monkeypatch, session, [[story]])
    with caplog.at_level(logging.ERROR):
        rank_clusters.main([])
    assert calls == []
    assert session.added == []
    assert "story_rank is missing" in caplog.text

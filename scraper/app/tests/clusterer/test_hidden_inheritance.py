"""A reminted cluster stays hidden when hidden articles are still a majority of it."""

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy.dialects import postgresql

from database.schema import Article, ArticleCluster, ClusterV2
from app.clusterer.run_clustering import hidden_member_ids, inherits_hidden, run_clustering


def _cluster(*article_ids: int, hidden: bool = False) -> ClusterV2:
    cluster = ClusterV2(title="Story", slug=f"story-{article_ids}", run_id=1, hidden=hidden)
    for article_id in article_ids:
        cluster.memberships.append(
            ArticleCluster(article_id=article_id, cluster_id=1, run_id=1)
        )
    return cluster


def test_nothing_hidden_is_a_no_op():
    previous = [_cluster(1, 2), _cluster(3)]
    assert hidden_member_ids(previous) == set()
    assert inherits_hidden([1, 2], hidden_member_ids(previous)) is False


def test_identical_membership_stays_hidden():
    previous = [_cluster(1, 2, 3, hidden=True)]
    hidden_ids = hidden_member_ids(previous)
    assert inherits_hidden([1, 2, 3], hidden_ids) is True


def test_majority_drift_stays_hidden():
    # Hash match only covers an identical set. Dropping one member and adding
    # one is still a majority of the new cluster.
    previous = [_cluster(1, 2, 3, hidden=True), _cluster(4, 5)]
    hidden_ids = hidden_member_ids(previous)
    assert inherits_hidden([2, 3, 9], hidden_ids) is True
    assert inherits_hidden([1, 2, 3, 9], hidden_ids) is True
    assert inherits_hidden([4, 5, 6], hidden_ids) is False


def test_one_shared_article_does_not_hide_a_large_cluster():
    # QA: a hidden pair loses one article to a 38-article cluster (39 members,
    # one of them hidden). That cluster must stay visible, and the next run's
    # hidden set must not grow to all 40 articles.
    hidden = {1, 2}
    big = [2, *range(3, 41)]
    assert len(big) == 39
    assert inherits_hidden(big, hidden) is False
    assert inherits_hidden([1], hidden) is True
    assert inherits_hidden([1, 2, 3, 4], hidden) is True
    assert inherits_hidden([1, 3, 4], hidden) is False
    next_hidden = hidden_member_ids([
        _cluster(1, hidden=True),
        _cluster(*big, hidden=False),
    ])
    assert next_hidden == {1}


def test_split_stays_hidden_and_a_minority_merge_does_not():
    previous = [_cluster(1, 2, 3, 4, hidden=True)]
    hidden_ids = hidden_member_ids(previous)
    assert inherits_hidden([1, 2], hidden_ids) is True
    assert inherits_hidden([3, 4], hidden_ids) is True
    assert inherits_hidden([1, 2, 3, 4, 5], hidden_ids) is True
    visible = set(range(10, 48))
    assert inherits_hidden([1, 2, *visible], hidden_ids) is False


class _Scalars:
    def __init__(self, values):
        self._values = list(values)

    def all(self):
        return list(self._values)


class _Session:
    def __init__(self, hidden_article_ids):
        self.hidden_article_ids = set(hidden_article_ids)
        self.statements = []

    def flush(self):
        return None

    def scalars(self, statement):
        self.statements.append(statement)
        return _Scalars(self.hidden_article_ids)


def _article(article_id, published_at):
    article = Article(
        url=f"https://example.test/{article_id}",
        title=f"Article {article_id}",
        published_at=published_at,
        deck=None,
        summary=None,
        author=None,
        content=None,
        embedding=[1.0, 0.0],
        image_urls=[],
        categories=[],
        llm_rank=None,
        is_paywalled=False,
        news_provider_key="test",
    )
    article.id = article_id
    return article


def _prev_cluster(cluster_id, article_ids, *, hidden, published_at):
    cluster = ClusterV2(title="Previous", slug=f"previous-{cluster_id}", run_id=1, hidden=hidden)
    cluster.id = cluster_id
    for article_id in article_ids:
        article = _article(article_id, published_at)
        membership = ArticleCluster(article_id=article_id, cluster_id=cluster_id, run_id=1)
        membership.article = article
        cluster.memberships.append(membership)
    return cluster


async def _run(monkeypatch, *, in_memory_hidden, hidden_at_start, hidden_during_enrich):
    """Run clustering with HDBSCAN, titles, and images replaced.

    The database's hidden articles change inside image lookup, the last slow
    step before insert. A read taken at the start of the run sees
    ``hidden_at_start`` and misses the value insert must use.
    """
    published_at = datetime.now(timezone.utc)
    small = _prev_cluster(10, (1, 2), hidden=in_memory_hidden, published_at=published_at)
    large = _prev_cluster(11, range(3, 41), hidden=False, published_at=published_at)
    session = _Session(hidden_at_start)

    def create(cluster_run):
        cluster_run.id = 7

    async def titles(groups, model):
        return [f"Title {index}" for index in range(len(groups))]

    async def enrich(payloads):
        session.hidden_article_ids = set(hidden_during_enrich)
        return payloads

    def regroup(articles):
        by_id = {article.id: article for article in articles}
        small_group = [by_id[1]]
        big_group = [by_id[article_id] for article_id in range(2, 41)]
        return {0: small_group, 1: big_group}, {article.id: 0.8 for article in articles}

    monkeypatch.setattr("app.clusterer.run_clustering.generate_cluster_titles", titles)
    monkeypatch.setattr("app.clusterer.run_clustering.enrich_cluster_payloads_with_wikimedia", enrich)
    monkeypatch.setattr("app.clusterer.run_clustering.cluster_with_confidence", regroup)
    saved = []
    uow = SimpleNamespace(
        cluster_runs=SimpleNamespace(
            get_latest=lambda: SimpleNamespace(id=1, clusters=[small, large]),
            create=create,
        ),
        session=session,
        articles=SimpleNamespace(get_all_since=lambda since: []),
        clusters_v2=SimpleNamespace(bulk_create=saved.extend),
    )
    await run_clustering(uow, SimpleNamespace())
    sql = "\n".join(
        str(statement.compile(dialect=postgresql.dialect())) for statement in session.statements
    )
    return saved, sql


@pytest.mark.asyncio
async def test_run_clustering_uses_a_hide_committed_before_insert(monkeypatch):
    saved, sql = await _run(
        monkeypatch, in_memory_hidden=False, hidden_at_start=set(), hidden_during_enrich={1, 2},
    )
    by_members = {
        tuple(sorted(member.article_id for member in cluster.memberships)): cluster
        for cluster in saved
    }
    assert by_members[(1,)].hidden is True
    big = tuple([2, *range(3, 41)])
    assert by_members[big].hidden is False
    assert "cluster_v2.hidden IS true" in sql
    assert "article_cluster.article_id" in sql


@pytest.mark.asyncio
async def test_run_clustering_drops_a_hide_cleared_before_insert(monkeypatch):
    saved, sql = await _run(
        monkeypatch, in_memory_hidden=True, hidden_at_start={1, 2}, hidden_during_enrich=set(),
    )
    assert saved
    assert all(cluster.hidden is False for cluster in saved)
    assert "cluster_v2.hidden IS true" in sql


def test_visible_overlap_does_not_hide_a_new_cluster():
    previous = [_cluster(1, 2, hidden=True), _cluster(3, 4)]
    hidden_ids = hidden_member_ids(previous)
    assert inherits_hidden([3, 4], hidden_ids) is False
    assert inherits_hidden([8, 9], hidden_ids) is False
    assert inherits_hidden([], hidden_ids) is False

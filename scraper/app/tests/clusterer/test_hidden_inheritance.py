"""A reminted cluster stays hidden when it still is the hidden story."""

from datetime import datetime, timezone
import logging
from types import SimpleNamespace

import pytest
from sqlalchemy.dialects import postgresql

from database.schema import Article, ArticleCluster, ClusterV2
from app.clusterer.run_clustering import hide_losses, inherits_hidden, run_clustering


def test_nothing_hidden_is_a_no_op():
    assert inherits_hidden([1, 2], []) is False


def test_identical_membership_stays_hidden():
    assert inherits_hidden([1, 2, 3], [{1, 2, 3}]) is True


def test_majority_drift_stays_hidden():
    # Hash match only covers an identical set. Dropping one member and adding
    # one is still a majority of the new cluster.
    hidden = [{1, 2, 3}]
    assert inherits_hidden([2, 3, 9], hidden) is True
    assert inherits_hidden([1, 2, 3, 9], hidden) is True
    assert inherits_hidden([4, 5, 6], hidden) is False


def test_one_shared_article_does_not_hide_a_large_cluster():
    # One article from a hidden pair joins 38 others (39 members). That is
    # half of the pair, not more, and it is not half of the new cluster.
    hidden = [{1, 2}]
    big = [2, *range(3, 41)]
    assert len(big) == 39
    assert inherits_hidden(big, hidden) is False
    assert inherits_hidden([1], hidden) is True
    assert inherits_hidden([1, 2, 3, 4], hidden) is True
    assert inherits_hidden([1, 3, 4], hidden) is False


def test_burst_of_new_articles_keeps_a_hidden_cluster():
    # 4 hidden + 5 new is 4/9 of the remint, under half, but it is the whole
    # hidden cluster and hidden articles are more than a quarter of the remint.
    hidden = [{1, 2, 3, 4}]
    assert inherits_hidden([1, 2, 3, 4, 5, 6, 7, 8, 9], hidden) is True
    # 4 hidden + 10 new is 4/14, still at least 25%.
    assert inherits_hidden(list(range(1, 15)), hidden) is True


def test_hidden_singleton_absorbed_by_a_large_cluster_is_dropped():
    # A 1-article hide inside 38 others is the whole hidden cluster, but only
    # 1/39 of the remint. It stays visible and the hide is dropped.
    big = [1, *range(2, 40)]
    assert len(big) == 39
    assert inherits_hidden(big, [{1}]) is False
    assert hide_losses({7: {1}}, [(set(big), False)]) == ([7], [])


def test_split_stays_hidden_and_a_minority_merge_does_not():
    hidden = [{1, 2, 3, 4}]
    assert inherits_hidden([1, 2], hidden) is True
    assert inherits_hidden([3, 4], hidden) is True
    assert inherits_hidden([1, 2, 3, 4, 5], hidden) is True
    visible = list(range(10, 48))
    assert inherits_hidden([1, 2, *visible], hidden) is False


def test_hide_is_dropped_only_when_every_remint_is_visible():
    hidden = {10: {1, 2}}
    visible_split = [({1, 3, 4, 5, 6}, False), ({2, 7, 8, 9, 10}, False)]
    assert hide_losses(hidden, visible_split) == ([10], [])
    # Article 1 stays in a hidden remint and article 2 leaks into a visible one.
    preserved = [({1}, True), ({2, *range(3, 41)}, False)]
    assert hide_losses(hidden, preserved) == ([], [10])
    assert hide_losses({11: set()}, visible_split) == ([], [])


class _Session:
    def __init__(self, hidden_article_ids, memberships):
        self.hidden_article_ids = set(hidden_article_ids)
        self.memberships = memberships
        self.statements = []

    def flush(self):
        return None

    def execute(self, statement):
        self.statements.append(statement)
        rows = [
            (cluster_id, article_id)
            for cluster_id, article_ids in self.memberships.items()
            for article_id in article_ids
            if article_id in self.hidden_article_ids
        ]
        return SimpleNamespace(all=lambda: rows)


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


async def _run(
    monkeypatch, *, in_memory_hidden, hidden_at_start, hidden_during_enrich, regroup=None,
    fail_commit=False,
):
    """Run clustering with HDBSCAN, titles, and images replaced.

    The database's hidden articles change inside image lookup, the last slow
    step before insert. A read taken at the start of the run sees
    ``hidden_at_start`` and misses the value insert must use.
    """
    published_at = datetime.now(timezone.utc)
    small = _prev_cluster(10, (1, 2), hidden=in_memory_hidden, published_at=published_at)
    large = _prev_cluster(11, range(3, 41), hidden=False, published_at=published_at)
    session = _Session(hidden_at_start, {10: {1, 2}, 11: set(range(3, 41))})

    def create(cluster_run):
        cluster_run.id = 7

    async def titles(groups, model):
        return [f"Title {index}" for index in range(len(groups))]

    async def enrich(payloads):
        session.hidden_article_ids = set(hidden_during_enrich)
        return payloads

    def default_regroup(articles):
        by_id = {article.id: article for article in articles}
        small_group = [by_id[1]]
        big_group = [by_id[article_id] for article_id in range(2, 41)]
        return {0: small_group, 1: big_group}, {article.id: 0.8 for article in articles}

    regroup = default_regroup if regroup is None else regroup

    monkeypatch.setattr("app.clusterer.run_clustering.generate_cluster_titles", titles)
    monkeypatch.setattr("app.clusterer.run_clustering.enrich_cluster_payloads_with_wikimedia", enrich)
    monkeypatch.setattr("app.clusterer.run_clustering.cluster_with_confidence", regroup)
    saved = []
    events = []
    original_warning = logging.warning

    def warning(message, *args, **kwargs):
        events.append("log")
        original_warning(message, *args, **kwargs)

    monkeypatch.setattr("app.clusterer.run_clustering.logging.warning", warning)

    def bulk_create(clusters):
        events.append("bulk_create")
        saved.extend(clusters)

    def commit():
        events.append("commit")
        if fail_commit:
            raise RuntimeError("commit failed")

    uow = SimpleNamespace(
        cluster_runs=SimpleNamespace(
            get_latest=lambda: SimpleNamespace(id=1, clusters=[small, large]),
            create=create,
        ),
        session=session,
        articles=SimpleNamespace(get_all_since=lambda since: []),
        clusters_v2=SimpleNamespace(bulk_create=bulk_create),
        commit=commit,
    )
    await run_clustering(uow, SimpleNamespace())
    sql = "\n".join(
        str(statement.compile(dialect=postgresql.dialect())) for statement in session.statements
    )
    return saved, sql, events


@pytest.mark.asyncio
async def test_run_clustering_uses_a_hide_committed_before_insert(monkeypatch):
    saved, sql, events = await _run(
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
    assert events[:2] == ["bulk_create", "commit"]


@pytest.mark.asyncio
async def test_run_clustering_drops_a_hide_cleared_before_insert(monkeypatch):
    saved, sql, _events = await _run(
        monkeypatch, in_memory_hidden=True, hidden_at_start={1, 2}, hidden_during_enrich=set(),
    )
    assert saved
    assert all(cluster.hidden is False for cluster in saved)
    assert "cluster_v2.hidden IS true" in sql


@pytest.mark.asyncio
async def test_run_clustering_warns_when_a_hide_lands_only_in_visible_clusters(
    monkeypatch, caplog,
):
    def split_across_two_visible_clusters(articles):
        by_id = {article.id: article for article in articles}
        left = [by_id[1], *[by_id[article_id] for article_id in range(3, 22)]]
        right = [by_id[2], *[by_id[article_id] for article_id in range(22, 41)]]
        return {0: left, 1: right}, {article.id: 0.8 for article in articles}

    with caplog.at_level("WARNING"):
        saved, _sql, events = await _run(
            monkeypatch,
            in_memory_hidden=False,
            hidden_at_start=set(),
            hidden_during_enrich={1, 2},
            regroup=split_across_two_visible_clusters,
        )
    assert saved
    assert all(cluster.hidden is False for cluster in saved)
    assert "Hide dropped for cluster 10" in caplog.text
    assert "Hide partially dropped" not in caplog.text
    assert events == ["bulk_create", "commit", "log"]


@pytest.mark.asyncio
async def test_hide_dropped_is_not_logged_when_commit_fails(monkeypatch, caplog):
    def split_across_two_visible_clusters(articles):
        by_id = {article.id: article for article in articles}
        left = [by_id[1], *[by_id[article_id] for article_id in range(3, 22)]]
        right = [by_id[2], *[by_id[article_id] for article_id in range(22, 41)]]
        return {0: left, 1: right}, {article.id: 0.8 for article in articles}

    with caplog.at_level("WARNING"):
        with pytest.raises(RuntimeError, match="commit failed"):
            await _run(
                monkeypatch,
                in_memory_hidden=False,
                hidden_at_start=set(),
                hidden_during_enrich={1, 2},
                regroup=split_across_two_visible_clusters,
                fail_commit=True,
            )
    assert "Hide dropped" not in caplog.text


def test_visible_overlap_does_not_hide_a_new_cluster():
    assert inherits_hidden([3, 4], [{1, 2}]) is False
    assert inherits_hidden([8, 9], [{1, 2}]) is False
    assert inherits_hidden([], [{1, 2}]) is False

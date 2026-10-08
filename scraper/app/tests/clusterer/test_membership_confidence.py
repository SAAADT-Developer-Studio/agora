import importlib
from types import SimpleNamespace

import numpy as np
import pytest

clustering = importlib.import_module("app.clusterer.cluster")


def test_membership_strength_follows_article_through_singleton_assignment(monkeypatch):
    class Model:
        labels_ = np.array([2, -1, 2])
        probabilities_ = np.array([0.9, 0.0, 0.35])

        def __init__(self, **params):
            assert params == clustering.HDBSCAN_PARAMS

        def fit(self, embeddings):
            assert len(embeddings) == 3
            return self

    monkeypatch.setattr(clustering.hdbscan, "HDBSCAN", Model)
    articles = [SimpleNamespace(id=id, embedding=[1.0, 0.0]) for id in (10, 20, 30)]
    groups, confidences = clustering.cluster_with_confidence(articles)
    assert [a.id for a in groups[2]] == [10, 30]
    assert [a.id for a in groups[3]] == [20]
    assert confidences == {10: 0.9, 20: None, 30: 0.35}


@pytest.mark.parametrize("count", [0, 1, 2])
def test_small_inputs_remain_valid_singletons(count):
    articles = [SimpleNamespace(id=id, embedding=[float(id), 1.0]) for id in range(count)]
    groups, confidences = clustering.cluster_with_confidence(articles)
    assert sum(len(group) for group in groups.values()) == count
    assert all(value is None for value in confidences.values())


@pytest.mark.asyncio
async def test_bootstrap_saves_clustering_params_and_membership_strength(monkeypatch):
    run = importlib.import_module("app.clusterer.run_clustering")
    from app.tests.ranking.test_persistence import stored_cluster
    articles = [stored_cluster().memberships[0].article]
    created = []
    clusters = []
    def create(value):
        value.id = 1
        created.append(value)
    uow = SimpleNamespace(
        cluster_runs=SimpleNamespace(create=create), session=SimpleNamespace(flush=lambda: None),
        articles=SimpleNamespace(get_latest=lambda count: articles),
        clusters_v2=SimpleNamespace(bulk_create=clusters.extend),
    )
    async def enrich(payloads):
        return payloads
    monkeypatch.setattr(run, "enrich_cluster_payloads_with_wikimedia", enrich)
    monkeypatch.setattr(run, "cluster_with_confidence", lambda articles: ({0: articles}, {1: 0.7}))
    await run.bootstrap_cluster_run(uow)
    assert created[0].params["hdbscan"] == clustering.HDBSCAN_PARAMS
    assert clusters[0].memberships[0].membership_confidence == 0.7


@pytest.mark.asyncio
@pytest.mark.parametrize("days", [None, 5])
async def test_bootstrap_without_api_calls_and_with_unique_slugs(monkeypatch, days):
    run = importlib.import_module("app.clusterer.run_clustering")
    from app.tests.ranking.test_persistence import stored_cluster
    articles = [stored_cluster(cluster_id=id).memberships[0].article for id in (1, 2)]
    created, clusters = [], []

    def get_latest(limit, **bounds):
        assert limit is None
        if days is None:
            assert not bounds
        else:
            from datetime import timedelta
            assert bounds["through"] - bounds["since"] == timedelta(days=days)
        return articles

    def create(value):
        value.id = 42
        created.append(value)

    async def unexpected_lookup(*args):
        pytest.fail("Bootstrap requested without external image lookups")

    uow = SimpleNamespace(
        cluster_runs=SimpleNamespace(create=create), session=SimpleNamespace(flush=lambda: None),
        articles=SimpleNamespace(get_latest=get_latest),
        clusters_v2=SimpleNamespace(bulk_create=clusters.extend),
    )
    monkeypatch.setattr(run, "enrich_cluster_payloads_with_wikimedia", unexpected_lookup)
    monkeypatch.setattr(run, "cluster_with_confidence", lambda values: ({0: values[:1], 1: values[1:]}, {1: None, 2: None}))
    await run.bootstrap_cluster_run(uow, article_limit=None, enrich_images=False, days=days)
    assert created[0].params["article_limit"] is None
    assert created[0].params["article_count"] == 2
    assert created[0].params["article_window_days"] == days
    assert len({c.slug for c in clusters}) == 2
    assert [m.article_id for c in clusters for m in c.memberships] == [1, 2]


@pytest.mark.asyncio
async def test_bootstrap_empty_database_creates_no_run():
    run = importlib.import_module("app.clusterer.run_clustering")
    uow = SimpleNamespace(articles=SimpleNamespace(get_latest=lambda count: []))
    await run.bootstrap_cluster_run(uow, article_limit=None, enrich_images=False)

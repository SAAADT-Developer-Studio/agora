from datetime import datetime, timedelta, timezone
import json

import pytest
from pydantic import ValidationError

from database.schema import Article, ArticleCluster, ClusterV2, NewsProvider
from app.ranking.contracts import RankableArticle, RankableCluster, RankingConfig
from app.ranking.engine import ClusterRankingExplanation
from app.ranking.persistence import (
    derive_cluster_category, prepare_cluster, rank_and_save_cluster, resolve_ranking_config,
)
from app.tests.ranking.samples import REPORT, PARAPHRASE, UPDATE

NOW = datetime(2026, 9, 13, 12, tzinfo=timezone.utc)


def stored_cluster(*, cluster_id=1, created_at=NOW, published_at=NOW - timedelta(hours=1)):
    provider = NewsProvider(key=f"publisher-{cluster_id}", name=f"Publisher {cluster_id}",
                            url=f"https://publisher-{cluster_id}.test", rank=0, bias_rating=None)
    article = Article(
        url=f"https://publisher.test/{cluster_id}", title="Council approves station",
        published_at=published_at, deck=None, summary="A new railway station.",
        author=None, content=REPORT, embedding=[1.0, 0.0], image_urls=[],
        categories=["sport"], llm_rank=8, is_paywalled=False, news_provider_key=provider.key,
    )
    article.id = cluster_id
    article.news_provider = provider
    cluster = ClusterV2(title="Station", slug=f"station-{cluster_id}", run_id=1)
    cluster.id = cluster_id
    cluster.created_at = created_at
    member = ArticleCluster(article_id=article.id, cluster_id=cluster.id, run_id=1,
                            membership_confidence=0.8)
    member.article = article
    cluster.memberships.append(member)
    return cluster


def test_snapshot_uses_stored_inputs_and_article_history_not_snapshot_birth():
    stored = stored_cluster(published_at=NOW - timedelta(days=40))
    snapshot = prepare_cluster(stored, NOW, RankingConfig(version="test"))
    assert snapshot.category == "sport"
    assert snapshot.created_at == NOW - timedelta(days=40)
    assert snapshot.articles[0].publisher_authority_score == 1
    assert snapshot.articles[0].cluster_membership_confidence == 0.8
    assert snapshot.articles[0].first_seen_at is None
    assert snapshot.articles[0].llm_rank == 8
    assert snapshot.articles[0].content == REPORT


@pytest.mark.parametrize("raw_rank", [0, -1, 11])
def test_invalid_stored_llm_rank_uses_missing_importance_without_changing_article(raw_rank, caplog):
    stored = stored_cluster()
    article = stored.memberships[0].article
    article.llm_rank = raw_rank
    config = RankingConfig(version="test")
    assert prepare_cluster(stored, NOW, config).articles[0].llm_rank is None
    result = rank_and_save_cluster(stored, NOW, config)
    assert result.newsworthiness.article_basis == "missing_scores"
    assert result.newsworthiness.reports[0].selection_reason == "missing_importance"
    assert article.llm_rank == raw_rank
    assert "using unknown importance" in caplog.text


@pytest.mark.parametrize("raw_rank", [None, 1, 10])
def test_valid_or_missing_stored_llm_rank_is_preserved(raw_rank):
    stored = stored_cluster()
    stored.memberships[0].article.llm_rank = raw_rank
    assert prepare_cluster(stored, NOW, RankingConfig(version="test")).articles[0].llm_rank == raw_rank


def test_save_records_explainable_bounded_score_and_resolved_configuration():
    stored = stored_cluster()
    config = resolve_ranking_config(RankingConfig(version="test"))
    result = rank_and_save_cluster(stored, NOW, config)
    assert 0 < stored.rank_score < 1
    assert stored.rank_score == result.result.score
    assert stored.ranked_at == NOW
    assert stored.rank_version == result.algorithm_version
    assert stored.rank_category == "sport"
    assert stored.rank_config["parameters"]["freshness"]["category_half_lives_hours"]["sport"] == 6
    assert stored.rank_config["version"] == "test"
    for name, value in result.result.components.model_dump().items():
        assert stored.rank_components[name] == value
    assert stored.rank_components["base_score"] * stored.rank_components["freshness_factor"] * stored.rank_components["confidence_factor"] == pytest.approx(stored.rank_score)


def test_dry_run_does_not_overwrite_any_existing_rank_data():
    stored = stored_cluster()
    config = resolve_ranking_config(RankingConfig(version="test"))
    rank_and_save_cluster(stored, NOW, config)
    original = {name: getattr(stored, name) for name in (
        "rank_score", "ranked_at", "rank_version", "rank_config", "rank_components", "rank_category",
    )}
    result = rank_and_save_cluster(stored, NOW + timedelta(days=7), config, dry_run=True)
    assert result.result.score < original["rank_score"]
    assert all(getattr(stored, name) == value for name, value in original.items())


def test_saved_explanation_survives_json_with_discounts_fallbacks_and_exclusions():
    stored = stored_cluster()
    for article_id in (2, 3, 4):
        member = stored_cluster(cluster_id=article_id).memberships[0]
        member.cluster_id = stored.id
        member.article.published_at += timedelta(minutes=article_id)
        stored.memberships.append(member)
    # Article 2 copies the first report; article 3 has missing ranking inputs;
    # article 4 was not yet observed when the score was calculated.
    missing = stored.memberships[2]
    missing.membership_confidence = None
    missing.article.content = None
    missing.article.summary = None
    missing.article.embedding = []
    missing.article.llm_rank = None
    stored.memberships[3].article.first_seen_at = NOW + timedelta(hours=1)

    calculated = rank_and_save_cluster(stored, NOW, RankingConfig(version="test"))
    payload = json.loads(json.dumps(stored.rank_components, allow_nan=False))
    saved = ClusterRankingExplanation.model_validate(payload["explanation"])

    assert saved == calculated
    assert saved.result.score == stored.rank_score
    assert sum(term.weighted_score for term in saved.terms) * saved.freshness_factor * saved.confidence_factor == pytest.approx(stored.rank_score)
    copy = next(item for item in saved.article_contribution.articles if item.article_id == 2)
    assert copy.family_representative_article_id == 1
    assert copy.family_multiplier < 1
    assert saved.article_contribution.syndicated_families[0].article_ids == (1, 2)
    assert saved.coverage.distinct_publisher_count == 3
    assert saved.coverage.effective_publisher_count < 3
    assert saved.publisher_authority.publishers
    assert saved.article_strength.publishers
    assert next(item for item in saved.momentum.articles if item.article_id == 2).reason == "syndicated_copy"
    assert next(item for item in saved.freshness.articles if item.article_id == 2).reason == "syndicated_copy"
    assert next(item for item in saved.newsworthiness.reports if item.representative_article_id == 3).selection_reason == "missing_importance"
    assert next(item for item in saved.article_contribution.articles if item.article_id == 3).fallback_signals
    assert next(item for item in saved.confidence.reports if item.representative_article_id == 3).used_membership_fallback
    for name in ("article_contribution", "coverage", "publisher_authority", "momentum",
                 "newsworthiness", "freshness", "confidence"):
        assert getattr(saved, name).excluded_article_ids == (4,)
        assert getattr(saved, name).evaluated_at == stored.ranked_at


def test_reranking_replaces_legacy_summary_with_current_full_explanation():
    stored = stored_cluster()
    stored.rank_components = {"coverage_score": 0.75}
    config = RankingConfig(version="test")
    rank_and_save_cluster(stored, NOW, config)
    previous = stored.rank_components

    later = NOW + timedelta(days=7)
    result = rank_and_save_cluster(stored, later, config)
    saved = ClusterRankingExplanation.model_validate(stored.rank_components["explanation"])
    assert saved == result
    assert saved.result.evaluated_at == later
    assert saved.result.score < previous["explanation"]["result"]["score"]
    assert ClusterRankingExplanation.model_validate(previous["explanation"]).result.evaluated_at == NOW


def test_missing_membership_stays_unknown_and_future_observation_is_excluded():
    stored = stored_cluster()
    stored.memberships[0].membership_confidence = None
    stored.memberships[0].article.first_seen_at = NOW + timedelta(hours=1)
    config = resolve_ranking_config(RankingConfig(version="test"))
    snapshot = prepare_cluster(stored, NOW, config)
    assert snapshot.category is None
    assert snapshot.articles[0].cluster_membership_confidence is None
    assert rank_and_save_cluster(stored, NOW, config).result.score == 0


def test_category_ignores_repeated_publishers_copies_and_future_articles():
    def article(id, publisher, category, content, **extra):
        return RankableArticle(article_id=id, publisher_key=publisher, title="Station",
                               published_at=NOW - timedelta(hours=2) + timedelta(seconds=id),
                               categories=(category,), content=content, **extra)
    articles = [
        article(1, "one", "kultura", REPORT),
        article(2, "two", "kultura", PARAPHRASE),
        article(3, "three", "sport", UPDATE),
        *[article(i, f"copy-{i}", "sport", REPORT) for i in range(4, 20)],
        *[article(i, "three", "sport", None) for i in range(20, 40)],
        *[article(i, f"future-{i}", "sport", None, first_seen_at=NOW + timedelta(hours=1)) for i in range(40, 60)],
    ]
    config = RankingConfig(version="test")
    assert derive_cluster_category(RankableCluster(cluster_id=1, articles=tuple(articles)), NOW, config) == "kultura"
    assert derive_cluster_category(RankableCluster(cluster_id=1, articles=tuple(reversed(articles))), NOW, config) == "kultura"


def test_config_defaults_are_materialized_without_losing_overrides():
    config = resolve_ranking_config(RankingConfig(version="custom", parameters={
        "ranking": {"coverage_weight": 3}, "freshness": {"default_half_life_hours": 10},
    }))
    assert config.parameters["ranking"]["coverage_weight"] == 3
    assert config.parameters["ranking"]["article_contribution_weight"] == 1
    assert config.parameters["freshness"]["default_half_life_hours"] == 10
    assert resolve_ranking_config(config) == config


@pytest.mark.parametrize("parameters", [{"typo": {}}, {"ranking": {"typo": 1}}, {"coverage": {"normalization_scale": 0}}])
def test_invalid_config_is_rejected_before_processing(parameters):
    with pytest.raises(ValueError):
        resolve_ranking_config(RankingConfig(version="test", parameters=parameters))


def test_mismatched_run_membership_is_rejected():
    stored = stored_cluster()
    stored.memberships[0].run_id = 2
    with pytest.raises(ValueError, match="different run"):
        prepare_cluster(stored, NOW, RankingConfig(version="test"))


def test_empty_cluster_is_not_given_a_fake_score():
    stored = stored_cluster()
    stored.memberships.clear()
    with pytest.raises(ValidationError):
        prepare_cluster(stored, NOW, RankingConfig(version="test"))

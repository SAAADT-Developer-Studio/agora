from datetime import datetime, timedelta, timezone
from itertools import permutations
from math import exp, isfinite
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from app.ranking import (
    ArticleStrengthConfig, ClusterNewsworthiness, ClusterRankingConfig, ClusterRankingExplanation,
    RankableArticle, RankableCluster, RankingComponentScores, RankingConfig, RankingFunction,
    RankingResult, explain_cluster_ranking, finalize_ranking, rank_cluster,
)
from app.tests.ranking.samples import REPORT, UPDATE


NOW = datetime(2026, 9, 13, 12, tzinfo=timezone.utc)


def article(article_id=1, **overrides):
    values = dict(
        article_id=article_id, publisher_key=f"publisher-{article_id}", title="Event report",
        published_at=NOW, llm_rank=7, publisher_authority_score=0.7,
        cluster_membership_confidence=0.9, embedding=(1.0, 0.0),
        content=" ".join(f"report{article_id}word{index}" for index in range(70)),
    )
    values.update(overrides)
    return RankableArticle(**values)


def explain(*articles, evaluated_at=NOW, category=None, newsworthiness=None, parameters=None, **ranking):
    settings = dict(parameters or {})
    settings["ranking"] = ranking
    return explain_cluster_ranking(
        RankableCluster(cluster_id=7, articles=articles, category=category, newsworthiness=newsworthiness),
        evaluated_at, RankingConfig(version="ranking-test-v1", parameters=settings),
    )


def only(term):
    return {name: float(name == term) for name in (
        "article_contribution_weight", "coverage_weight", "momentum_weight", "semantic_importance_weight",
    )}


def test_default_composition_has_documented_values_and_applies_each_gate_once():
    result = explain(article(1), article(2))
    components = result.result.components
    assert components.article_contribution_score == pytest.approx(0.6425)
    assert components.coverage_score == pytest.approx(1 - exp(-2 / 5))
    assert components.momentum_score == pytest.approx(1 - exp(-2 / 3))
    assert components.semantic_importance_score == pytest.approx(2 / 3)
    assert components.publisher_authority_score == pytest.approx(0.7)
    assert components.freshness_score == 1
    assert components.cluster_confidence_score == pytest.approx(0.97)
    expected_base = (0.6425 + 1 - exp(-2 / 5) + 1 - exp(-2 / 3) + 2 / 3) / 4
    assert result.base_score == pytest.approx(expected_base)
    assert result.result.score == pytest.approx(expected_base * 0.97)
    assert result.freshness_factor == 1
    assert result.confidence_factor == pytest.approx(0.97)
    assert all(term.weight == 0.25 for term in result.terms)
    assert result.algorithm_version == "cluster-ranking-v1"
    assert result.result.config_version == "ranking-test-v1"


def test_public_scorer_implements_the_existing_ranking_function_contract():
    cluster = RankableCluster(cluster_id=7, articles=(article(1), article(2)))
    config = RankingConfig(version="test")
    scorer: RankingFunction = rank_cluster
    result = scorer(cluster, NOW, config)
    assert isinstance(result, RankingResult)
    assert result == explain_cluster_ranking(cluster, NOW, config).result
    assert result.cluster_id == cluster.cluster_id
    assert result.model_dump(mode="json")["evaluated_at"] == "2026-09-13T12:00:00Z"
    assert RankingResult.model_validate_json(result.model_dump_json()) == result


@pytest.mark.parametrize("component, weight", [
    ("article_contribution_score", "article_contribution_weight"),
    ("coverage_score", "coverage_weight"), ("momentum_score", "momentum_weight"),
    ("semantic_importance_score", "semantic_importance_weight"),
])
def test_each_positive_component_can_be_used_alone_without_other_terms_leaking_in(component, weight):
    result = explain(article(1), article(2), **only(weight))
    assert result.base_score == getattr(result.result.components, component)
    assert result.result.score == pytest.approx(result.base_score * result.freshness_factor * result.confidence_factor)
    assert sum(term.weight for term in result.terms) == 1
    assert [term.component for term in result.terms if term.weight] == [component]


def test_relative_weights_are_configuration_constants_not_cross_cluster_normalization():
    weights = dict(article_contribution_weight=1, coverage_weight=2, momentum_weight=3, semantic_importance_weight=4)
    result = explain(article(1), article(2), **weights)
    scaled = explain(article(1), article(2), **{key: value * 100 for key, value in weights.items()})
    assert [term.weight for term in result.terms] == pytest.approx([0.1, 0.2, 0.3, 0.4])
    assert result.result == scaled.result
    assert result.base_score == pytest.approx(sum(term.weighted_score for term in result.terms))


@pytest.mark.parametrize("weight", [1e308, 5e-324])
def test_extreme_positive_weights_remain_finite_without_overflow_or_underflow(weight):
    base_weights = {key: weight for key in only("article_contribution_weight")}
    result = explain(article(1), article(2), **base_weights,
                     article_strength={"authority_weight": weight, "data_quality_weight": weight, "source_weight": weight})
    assert all(term.weight == 0.25 for term in result.terms)
    assert result.article_strength.authority_weight == pytest.approx(1 / 3)
    assert result.article_strength.data_quality_weight == pytest.approx(1 / 3)
    assert result.article_strength.source_weight == pytest.approx(1 / 3)
    assert isfinite(result.result.score) and 0 <= result.result.score <= 1


def test_article_strength_reuses_quality_signals_instead_of_age_and_volume_adjusted_totals():
    result = explain(article(1), article(2))
    strength = result.article_strength
    assert strength.mean_data_quality == pytest.approx(0.475)
    assert strength.mean_source_credit == 0.75
    assert strength.publisher_authority_score == pytest.approx(0.7)
    assert strength.article_contribution_score == result.result.components.article_contribution_score
    assert strength.article_contribution_score != result.article_contribution.article_contribution_score
    assert [report.article_id for report in strength.publishers] == [1, 2]
    assert strength.basis == "available"


def test_original_standalone_contribution_scaling_does_not_leak_into_composition():
    reports = (article(1), article(2, publisher_key="publisher-1"), article(3))
    baseline = explain(*reports)
    changed = explain(*reports, parameters={"article_contribution": {
        "freshness_half_life_hours": 0.01, "normalization_scale": 100,
        "publisher_repeat_decay": 0.01, "authority_weight": 0.01,
        "novelty_weight": 1, "originality_weight": 0.01,
    }})
    assert changed.article_contribution.article_contribution_score != baseline.article_contribution.article_contribution_score
    assert changed.result == baseline.result


def test_per_article_decay_is_not_applied_again_on_top_of_event_freshness():
    reports = (article(1), article(2))
    before = explain(*reports, momentum_weight=0)
    after = explain(*reports, evaluated_at=NOW + timedelta(hours=24), momentum_weight=0)
    assert after.article_contribution.total_contribution == pytest.approx(before.article_contribution.total_contribution / 2)
    assert after.result.components.article_contribution_score == before.result.components.article_contribution_score
    assert after.base_score == before.base_score
    assert after.confidence_factor == before.confidence_factor
    assert after.freshness_factor == 0.5
    assert after.result.score == pytest.approx(before.result.score / 2)


def test_authority_is_counted_once_inside_article_strength_not_as_an_extra_base_term():
    result = explain(article(1), article(2), **only("article_contribution_weight"),
                     article_strength={"authority_weight": 1, "data_quality_weight": 0, "source_weight": 0})
    assert result.base_score == result.result.components.publisher_authority_score == pytest.approx(0.7)
    assert all(term.component != "publisher_authority_score" for term in result.terms)


def test_authority_fallback_has_one_owner_in_the_composed_score():
    reports = (article(1, publisher_authority_score=None), article(2, publisher_authority_score=None))
    result = explain(*reports, parameters={
        "publisher_authority": {"unknown_authority": 0.2},
        "article_contribution": {"unknown_authority": 0.9},
    }, **only("article_contribution_weight"),
        article_strength={"authority_weight": 1, "data_quality_weight": 0, "source_weight": 0})
    assert result.base_score == pytest.approx(0.2)
    assert all(publisher.used_fallback for publisher in result.publisher_authority.publishers)
    assert all(item.publisher_authority == 0.9 for item in result.article_contribution.articles)


def test_publisher_repetition_cannot_add_another_quality_vote():
    baseline = explain(article(1), article(2))
    repeated = explain(article(1), article(2), *(article(index, publisher_key=" PUBLISHER-1 ") for index in range(3, 23)))
    assert repeated.article_strength == baseline.article_strength
    assert len(repeated.article_strength.publishers) == 2


def test_article_selection_keeps_quality_and_source_credit_from_the_same_report():
    first = article(1, publisher_key="p", is_primary_source=True, published_at=NOW - timedelta(hours=2))
    longer = article(2, publisher_key="p", is_primary_source=False,
                     content=" ".join(f"longerword{index}" for index in range(200)))
    result = explain(first, longer)
    assert result.article_strength.publishers[0].article_id == 1
    assert result.article_strength.mean_data_quality == result.article_contribution.articles[0].data_quality
    assert result.article_strength.mean_source_credit == 1
    assert result.article_strength.mean_data_quality < result.article_contribution.articles[1].data_quality


def test_copy_distribution_has_only_bounded_coverage_credit_and_no_new_quality_momentum_or_importance():
    original = article(1, content=REPORT)
    baseline = explain(original)
    copied = explain(original, *(article(index, content=REPORT, llm_rank=10) for index in range(2, 42)))
    assert copied.article_strength.publishers == baseline.article_strength.publishers
    assert copied.article_strength.article_contribution_score == pytest.approx(baseline.article_strength.article_contribution_score)
    assert copied.result.components.momentum_score == baseline.result.components.momentum_score
    assert copied.result.components.semantic_importance_score == baseline.result.components.semantic_importance_score
    assert copied.freshness_factor == baseline.freshness_factor
    assert copied.confidence_factor == baseline.confidence_factor
    assert copied.coverage.effective_publisher_count <= 1.15
    assert copied.base_score - baseline.base_score == pytest.approx(
        (copied.coverage.coverage_score - baseline.coverage.coverage_score) / 4,
    )


def test_same_publisher_exact_copies_leave_the_final_score_unchanged():
    original = article(1, content=REPORT, publisher_key="p")
    copied = explain(original, *(article(index, content=REPORT, publisher_key="p") for index in range(2, 22)))
    assert copied.result == explain(original).result


def test_known_standalone_copy_does_not_become_an_intrinsic_quality_report():
    result = explain(article(is_syndicated=True, is_primary_source=True, publisher_authority_score=1, llm_rank=10))
    assert result.article_strength.basis == "no_qualifying_reports"
    assert result.result.components.article_contribution_score == 0
    assert result.result.score == 0


def test_large_coherent_inputs_saturate_and_keep_every_component_and_gate_bounded():
    results = [explain(*(article(index) for index in range(1, count + 1))) for count in (3, 20, 40, 80)]
    assert all(item.article_strength.article_contribution_score == pytest.approx(0.6425) for item in results)
    for item in results:
        assert all(0 <= value <= 1 for value in item.result.components.model_dump().values())
        assert 0 <= item.result.score <= item.base_score <= 1
        assert item.result.score <= item.freshness_factor
        assert item.result.score <= item.confidence_factor
    assert results[-1].result.score - results[-2].result.score < results[1].result.score - results[0].result.score
    assert results[-1].article_contribution.total_contribution > 1  # Raw diagnostics are never added to base.


def test_large_badly_formed_cluster_is_gated_despite_strong_other_components():
    reports = [article(index + 1, embedding=tuple(float(index == axis) for axis in range(12)), llm_rank=10)
               for index in range(12)]
    result = explain(*reports)
    assert result.base_score > 0.5
    assert result.confidence.semantic_coherence_score == 0
    assert result.confidence_factor == pytest.approx(0.27)
    assert result.result.score == pytest.approx(
        result.base_score * result.freshness_factor * result.confidence_factor
    )
    assert result.result.score < result.base_score


def test_category_changes_event_decay_without_changing_base_importance():
    reports = (article(1, published_at=NOW - timedelta(hours=24)), article(2, published_at=NOW - timedelta(hours=24)))
    fast = explain(*reports, category="sport")
    slow = explain(*reports, category="kultura")
    assert fast.base_score == slow.base_score
    assert fast.confidence_factor == slow.confidence_factor
    assert fast.freshness_factor < slow.freshness_factor
    assert fast.result.score < slow.result.score


def test_zero_llm_importance_is_a_real_score_while_missing_importance_uses_explicit_fallback():
    zero = explain(article(1, llm_rank=1), article(2, llm_rank=1), **only("semantic_importance_weight"))
    unknown = explain(article(1, llm_rank=None), article(2, llm_rank=None), **only("semantic_importance_weight"))
    assert zero.base_score == zero.result.score == 0
    assert unknown.base_score == 0.5
    assert unknown.newsworthiness.source == "fallback"


def test_missing_components_keep_their_configured_weights_instead_of_redistributing_them():
    unknown = article(embedding=(), content=None, llm_rank=None,
                      publisher_authority_score=None, cluster_membership_confidence=None)
    result = explain(unknown)
    assert result.momentum.momentum_score == 0
    assert all(term.weight == 0.25 for term in result.terms)
    assert result.newsworthiness.article_basis == "missing_scores"
    assert result.confidence.basis == "fallback"
    assert result.freshness.anchor_basis == "first_report_fallback"
    assert result.article_strength.publishers[0].used_unknown_content
    assert all(publisher.used_fallback for publisher in result.publisher_authority.publishers)
    # Single-article confidence is 0.5 and the gate power is 1, so a thin
    # snapshot stays small without being forced under the old squared gate.
    assert 0 < result.result.score < 0.2


def test_all_future_input_yields_zero_without_a_neutral_fallback_score():
    result = explain(article(published_at=NOW + timedelta(hours=1)))
    assert result.base_score == result.result.score == 0
    assert all(value == 0 for value in result.result.components.model_dump().values())
    assert result.article_strength.basis == "unavailable"
    assert result.article_contribution.excluded_article_ids == (1,)


def test_future_publications_and_first_seen_observations_are_excluded_consistently():
    reports = (article(1), article(2))
    result = explain(*reports, article(3, published_at=NOW + timedelta(seconds=1), llm_rank=10),
                     article(4, first_seen_at=NOW + timedelta(seconds=1), embedding=(0.0, 1.0)))
    assert result.result == explain(*reports).result
    for component in (result.article_contribution, result.coverage, result.publisher_authority,
                      result.momentum, result.newsworthiness, result.freshness, result.confidence):
        assert component.excluded_article_ids == (3, 4)


def test_an_unrelated_cluster_cannot_change_this_clusters_normalization():
    target = RankableCluster(cluster_id=7, articles=(article(1), article(2)))
    unrelated = RankableCluster(cluster_id=8, articles=tuple(article(index, llm_rank=10) for index in range(1, 21)))
    config = RankingConfig(version="test")
    before = rank_cluster(target, NOW, config)
    rank_cluster(unrelated, NOW, config)
    assert rank_cluster(target, NOW, config) == before


def test_precomputed_cluster_llm_evaluation_flows_through_the_existing_semantic_component():
    result = explain(article(1), article(2), newsworthiness=ClusterNewsworthiness(
        score=0.9, evaluated_at=NOW, version="cluster-llm-v1",
    ), **only("semantic_importance_weight"))
    assert result.base_score == result.result.components.semantic_importance_score == 0.9
    assert result.result.score == pytest.approx(0.9 * result.freshness_factor * result.confidence_factor)
    assert result.newsworthiness.source == "cluster_evaluation"


def test_finalizer_applies_freshness_and_confidence_once_to_an_ungated_base():
    components = RankingComponentScores(
        article_contribution_score=1, coverage_score=1, momentum_score=1, semantic_importance_score=1,
        publisher_authority_score=1, freshness_score=0.5, cluster_confidence_score=0.2,
    )
    result = finalize_ranking(cluster_id=7, base_score=0.8, components=components, evaluated_at=NOW,
                              config=RankingConfig(version="test"))
    assert result.score == pytest.approx(0.08)
    assert result.components == components


def test_small_freshness_cannot_allow_an_unbounded_base_to_bypass_validation():
    components = RankingComponentScores(
        article_contribution_score=1, coverage_score=1, momentum_score=1, semantic_importance_score=1,
        publisher_authority_score=1, freshness_score=0.01, cluster_confidence_score=0.2,
    )
    with pytest.raises(ValidationError):
        finalize_ranking(cluster_id=7, base_score=50, components=components, evaluated_at=NOW,
                         config=RankingConfig(version="test"))


def test_input_order_timezones_and_serialization_preserve_reproducible_explanations():
    reports = (article(1, content=REPORT), article(2, content=REPORT), article(3, content=UPDATE))
    result = explain(*reports)
    assert all(explain(*order) == result for order in permutations(reports))
    assert explain(*reports, evaluated_at=NOW.astimezone(ZoneInfo("Europe/Ljubljana"))) == result
    assert ClusterRankingExplanation.model_validate_json(result.model_dump_json()) == result


def test_engine_does_not_mutate_cluster_configuration_or_component_models():
    cluster = RankableCluster(cluster_id=7, articles=(article(1), article(2)))
    config = RankingConfig(version="test", parameters={"ranking": {"coverage_weight": 2}})
    before = cluster.model_dump_json(), config.model_dump_json()
    explanation = explain_cluster_ranking(cluster, NOW, config)
    assert (cluster.model_dump_json(), config.model_dump_json()) == before
    with pytest.raises(ValidationError):
        explanation.base_score = 1
    with pytest.raises(ValidationError):
        explanation.terms[0].weight = 1
    with pytest.raises(ValidationError):
        explanation.article_strength.publishers[0].data_quality = 1


def test_conflicting_authority_is_reported_instead_of_silently_hidden_by_composition():
    with pytest.raises(ValueError, match="conflicting authority"):
        explain(article(1, publisher_key="p", publisher_authority_score=0.1),
                article(2, publisher_key="p", publisher_authority_score=0.9))


@pytest.mark.parametrize("parameters", [
    {key: 0 for key in only("article_contribution_weight")},
    {"article_contribution_weight": -1}, {"coverage_weight": -1},
    {"momentum_weight": -1}, {"semantic_importance_weight": -1},
    {"publisher_authority_weight": 1}, {"freshness_weight": 1}, {"confidence_weight": 1},
    {"article_strength": {"authority_weight": 0, "data_quality_weight": 0, "source_weight": 0}},
    {"article_strength": {"authority_weight": -1}},
    {"article_strength": {"data_quality_weight": -1}},
    {"article_strength": {"source_weight": -1}},
    {"article_strength": {"novelty_weight": 1}},
    {"article_strength": {"freshness_weight": 1}},
    {"typo": 1},
])
def test_invalid_or_overlapping_composition_parameters_are_rejected(parameters):
    with pytest.raises(ValidationError):
        explain(article(), **parameters)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
def test_nonfinite_weights_are_rejected(value):
    for parameter in only("article_contribution_weight"):
        with pytest.raises(ValidationError):
            ClusterRankingConfig(**{parameter: value})
    for parameter in ArticleStrengthConfig.model_fields:
        with pytest.raises(ValidationError):
            ArticleStrengthConfig(**{parameter: value})


def test_invalid_component_configuration_is_not_swallowed_as_missing_data():
    with pytest.raises(ValidationError):
        explain(article(), parameters={"freshness": {"default_half_life_hours": 0}})


def _near(cosine: float) -> tuple[float, float]:
    return (cosine, (1.0 - cosine * cosine) ** 0.5)


def _story_article(article_id, publisher, published_at, cosine, llm_rank=8):
    return article(
        article_id, publisher_key=publisher, published_at=published_at, llm_rank=llm_rank,
        embedding=_near(cosine), cluster_membership_confidence=0.85,
        content=" ".join(f"outlet{publisher}report{article_id}word{index}" for index in range(70)),
    )


def test_fresh_multi_source_story_outranks_old_big_story_and_a_single_article():
    fresh = rank_cluster(RankableCluster(cluster_id=1, articles=(
        _story_article(1, "rtvslo", NOW - timedelta(hours=2), 1.0),
        _story_article(2, "24ur", NOW - timedelta(hours=2), 0.93),
        _story_article(3, "delo", NOW - timedelta(hours=1), 0.88),
    )), NOW, RankingConfig(version="feed-order"))
    old = rank_cluster(RankableCluster(cluster_id=2, articles=tuple(
        _story_article(10 + index, f"archive-{index}", NOW - timedelta(hours=30), 0.9 + index / 200, llm_rank=9)
        for index in range(8)
    )), NOW, RankingConfig(version="feed-order"))
    single = rank_cluster(RankableCluster(cluster_id=3, articles=(
        _story_article(30, "local", NOW - timedelta(hours=1), 1.0),
    )), NOW, RankingConfig(version="feed-order"))
    assert fresh.score > old.score > single.score


def test_one_outlet_posting_many_times_does_not_beat_several_outlets():
    repeated = rank_cluster(RankableCluster(cluster_id=1, articles=tuple(
        _story_article(index, "rtvslo", NOW - timedelta(minutes=20 * index), min(0.99, 0.85 + index / 100))
        for index in range(1, 16)
    )), NOW, RankingConfig(version="outlets"))
    several = rank_cluster(RankableCluster(cluster_id=2, articles=tuple(
        _story_article(20 + index, publisher, NOW - timedelta(hours=1), 0.9 + index / 50)
        for index, publisher in enumerate(("rtvslo", "24ur", "delo", "vecer"))
    )), NOW, RankingConfig(version="outlets"))
    assert repeated.components.cluster_confidence_score == 0.5
    assert several.components.cluster_confidence_score > repeated.components.cluster_confidence_score
    assert several.score > repeated.score


def test_naive_evaluation_time_is_rejected():
    with pytest.raises(ValueError, match="timezone"):
        explain(article(), evaluated_at=NOW.replace(tzinfo=None))

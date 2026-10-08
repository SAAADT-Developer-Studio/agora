from datetime import datetime, timedelta, timezone
from itertools import permutations
from math import isfinite
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from app.ranking import (
    ClusterConfidenceConfig, ClusterConfidenceResult, RankableArticle, RankableCluster,
    RankingComponentScores, RankingConfig, apply_confidence_gate, finalize_ranking,
    score_cluster_confidence,
)
from app.tests.ranking.samples import REPORT, UPDATE


NOW = datetime(2026, 9, 13, 12, tzinfo=timezone.utc)
CONFIG = RankingConfig(version="confidence-test-v1")


def article(article_id=1, **overrides):
    values = dict(
        article_id=article_id, publisher_key=f"publisher-{article_id}",
        title="Event report", published_at=NOW - timedelta(hours=2), embedding=(1.0, 0.0),
        cluster_membership_confidence=0.9,
        content=" ".join(f"report{article_id}word{index}" for index in range(70)),
    )
    values.update(overrides)
    return RankableArticle(**values)


def score(*articles, evaluated_at=NOW, **parameters):
    return score_cluster_confidence(
        RankableCluster(cluster_id=7, articles=articles), evaluated_at,
        RankingConfig(version=CONFIG.version, parameters={"cluster_confidence": parameters}),
    )


def components(confidence):
    return RankingComponentScores(
        coverage_score=1, momentum_score=1, freshness_score=1, article_contribution_score=1,
        publisher_authority_score=1, semantic_importance_score=1, cluster_confidence_score=confidence,
    )


def test_coherent_reports_expose_all_signals_and_the_confidence_gate():
    result = score(article(1), article(2), article(3))
    assert result.semantic_coherence_score == result.semantic_data_fraction == 1
    assert result.membership_confidence_score == pytest.approx(0.9)
    assert result.membership_data_fraction == result.temporal_coherence_score == 1
    assert result.signal_confidence_score == result.cluster_confidence_score == pytest.approx(0.97)
    assert result.gate_multiplier == pytest.approx(0.97 ** 2)
    assert result.outlier_proportion == result.weakly_related_proportion == 0
    assert result.embedding_dimension == 2
    assert result.compared_report_count == result.effective_report_weight == 3
    assert result.temporal_center_at == NOW - timedelta(hours=2)
    assert result.mean_temporal_deviation_hours == 0
    assert all(report.peer_centroid_similarity == 1 for report in result.reports)
    assert all(report.embedding_status == "compared" for report in result.reports)
    assert result.basis == "measured"
    assert result.algorithm_version == "cluster-confidence-v1"
    assert result.syndication_algorithm_version == "syndication-v1"
    assert result.config_version == CONFIG.version
    assert result.model_dump(mode="json")["evaluated_at"] == "2026-09-13T12:00:00Z"
    assert ClusterConfidenceResult.model_validate_json(result.model_dump_json()) == result


def test_two_unrelated_reports_cannot_get_false_confidence_from_their_own_centroid_vectors():
    result = score(article(1, embedding=(1.0, 0.0)), article(2, embedding=(0.0, 1.0)))
    assert [report.peer_centroid_similarity for report in result.reports] == [0, 0]
    assert result.outlier_proportion == result.weakly_related_proportion == 1
    assert result.cluster_confidence_score == result.gate_multiplier == 0


def test_a_singleton_has_no_semantic_peer_instead_of_perfect_similarity():
    result = score(article(cluster_membership_confidence=None))
    assert result.reports[0].embedding_status == "no_peers"
    assert result.reports[0].peer_centroid_similarity is None
    assert result.semantic_data_fraction == 0
    assert result.cluster_confidence_score == 0.5
    assert result.gate_multiplier == 0.25
    assert result.basis == "fallback"


def test_outliers_lower_confidence_even_when_membership_values_are_high():
    coherent = [article(index) for index in range(1, 4)]
    result = score(*coherent, article(4, embedding=(0.0, 1.0), cluster_membership_confidence=1))
    assert result.outlier_proportion == result.weakly_related_proportion == 0.25
    assert result.reports[3].is_outlier
    assert result.reports[3].peer_centroid_similarity == 0
    assert result.cluster_confidence_score < score(*coherent).cluster_confidence_score
    assert result.gate_multiplier < 0.3


def test_weakly_related_reports_are_penalized_separately_from_clear_outliers():
    result = score(article(1), article(2, embedding=(0.6, 0.8)))
    assert result.outlier_proportion == 0
    assert result.weakly_related_proportion == 1
    assert result.semantic_coherence_score == pytest.approx(0.4)
    assert result.cluster_confidence_score == pytest.approx(result.signal_confidence_score * 0.5)
    assert all(report.is_weakly_related and not report.is_outlier for report in result.reports)


def test_balanced_unrelated_subgroups_remain_low_confidence_even_when_large():
    reports = [article(index, embedding=(1.0, 0.0) if index <= 20 else (0.0, 1.0))
               for index in range(1, 41)]
    result = score(*reports)
    assert result.weakly_related_proportion == 1
    assert result.cluster_confidence_score < 0.4
    assert result.gate_multiplier < 0.16


def test_many_mutually_unrelated_reports_cannot_become_confident_through_volume():
    for count in (2, 12):
        reports = [article(index + 1, embedding=tuple(float(axis == index) for axis in range(count)))
                   for index in range(count)]
        result = score(*reports)
        assert result.cluster_confidence_score == result.gate_multiplier == 0
        assert result.outlier_proportion == 1


def test_coherent_report_count_does_not_add_a_confidence_bonus():
    small = score(article(1), article(2))
    large = score(*(article(index) for index in range(1, 31)))
    assert large.cluster_confidence_score == pytest.approx(small.cluster_confidence_score)
    assert large.gate_multiplier == pytest.approx(small.gate_multiplier)


def test_opposing_vectors_are_incoherent_instead_of_missing_data():
    result = score(article(1), article(2, embedding=(-1.0, 0.0)))
    assert [report.peer_centroid_similarity for report in result.reports] == [-1, -1]
    assert result.cluster_confidence_score == 0
    assert result.semantic_data_fraction == 1


def test_cancelling_peer_centroid_is_a_measured_failure_not_an_unknown_fallback():
    result = score(article(1), article(2, embedding=(-1.0, 0.0)), article(3, embedding=(0.0, 1.0)))
    report = result.reports[2]
    assert report.embedding_status == "cancelled_peer_centroid"
    assert report.peer_centroid_similarity is None
    assert report.similarity_score == 0
    assert report.is_outlier and not report.used_semantic_fallback
    assert result.semantic_data_fraction == 1
    assert result.cluster_confidence_score == 0


def test_membership_confidence_matters_with_identical_embeddings():
    high = score(article(1, cluster_membership_confidence=1), article(2, cluster_membership_confidence=1))
    medium = score(article(1, cluster_membership_confidence=0.6), article(2, cluster_membership_confidence=0.6))
    weak = score(article(1, cluster_membership_confidence=0.3), article(2, cluster_membership_confidence=0.3))
    outlier = score(article(1, cluster_membership_confidence=0.1), article(2, cluster_membership_confidence=0.1))
    assert high.cluster_confidence_score > medium.cluster_confidence_score > weak.cluster_confidence_score > outlier.cluster_confidence_score
    assert high.cluster_confidence_score == 1
    assert weak.weakly_related_proportion == 1 and weak.outlier_proportion == 0
    assert outlier.outlier_proportion == 1 and outlier.cluster_confidence_score == 0


def test_missing_membership_uses_an_explicit_fallback_instead_of_zero_or_one():
    result = score(article(1, cluster_membership_confidence=None), article(2, cluster_membership_confidence=None))
    assert result.membership_confidence_score == 0.5
    assert result.membership_data_fraction == 0
    assert result.cluster_confidence_score == 0.85
    assert all(report.used_membership_fallback for report in result.reports)
    assert result.weakly_related_proportion == result.outlier_proportion == 0


def test_zero_membership_is_not_treated_as_missing():
    result = score(article(1, cluster_membership_confidence=0), article(2, cluster_membership_confidence=0))
    assert result.membership_confidence_score == 0
    assert result.membership_data_fraction == 1
    assert result.cluster_confidence_score == 0


@pytest.mark.parametrize("embedding, status", [((), "missing"), ((0.0, 0.0), "zero_vector")])
def test_unusable_embeddings_are_explicit_and_cannot_claim_perfect_coherence(embedding, status):
    result = score(article(1, embedding=embedding, cluster_membership_confidence=None),
                   article(2, embedding=embedding, cluster_membership_confidence=None))
    assert result.embedding_dimension is None
    assert result.semantic_data_fraction == 0
    assert result.cluster_confidence_score == 0.5
    assert all(report.embedding_status == status for report in result.reports)
    assert all(report.used_semantic_fallback for report in result.reports)


def test_sparse_valid_embeddings_do_not_hide_the_missing_majority():
    result = score(article(1), article(2), *(article(index, embedding=()) for index in range(3, 11)))
    assert result.semantic_data_fraction == 0.2
    assert result.semantic_coherence_score == pytest.approx(0.6)
    assert result.cluster_confidence_score < score(article(1), article(2)).cluster_confidence_score


def test_mixed_dimensions_are_not_compared_or_silently_dropped():
    result = score(article(1), article(2), article(3, embedding=(1.0, 0.0, 0.0)))
    assert result.embedding_dimension == 2
    assert result.reports[2].embedding_status == "incompatible_dimension"
    assert result.semantic_data_fraction == pytest.approx(2 / 3)
    assert result.semantic_coherence_score == pytest.approx(5 / 6)


def test_dimension_selection_uses_publisher_support_instead_of_raw_article_count():
    result = score(*(article(index, publisher_key="repeat", embedding=(1.0, 0.0, 0.0))
                     for index in range(1, 11)), article(11), article(12))
    assert result.embedding_dimension == 2
    assert result.effective_report_weight == 3
    assert result.semantic_data_fraction == pytest.approx(2 / 3)
    assert all(report.weight == 0.1 for report in result.reports[:10])


def test_equal_dimension_support_has_a_deterministic_tie_break():
    result = score(article(1, embedding=(1.0, 0.0, 0.0)), article(2))
    assert result.embedding_dimension == 2
    assert result.semantic_data_fraction == 0
    assert result.reports[0].embedding_status == "incompatible_dimension"
    assert result.reports[1].embedding_status == "no_peers"


@pytest.mark.parametrize("scale", [1e308, 1e-300, 5e-324])
def test_vector_magnitude_cannot_change_cosine_coherence_or_overflow(scale):
    result = score(article(1, embedding=(scale, scale)), article(2, embedding=(scale, scale)))
    assert all(isfinite(report.peer_centroid_similarity) for report in result.reports)
    assert all(report.peer_centroid_similarity == pytest.approx(1) for report in result.reports)
    assert result.cluster_confidence_score == pytest.approx(0.97)


def test_nonfinite_input_embeddings_are_rejected_by_the_contract():
    for value in (float("nan"), float("inf"), -float("inf")):
        with pytest.raises(ValidationError):
            article(embedding=(value, 1.0))


def test_syndicated_copies_cannot_hide_an_outlier_or_shift_temporal_coherence():
    original = article(1, content=REPORT, published_at=NOW - timedelta(hours=5))
    unrelated = article(2, content=UPDATE, embedding=(0.0, 1.0))
    before = score(original, unrelated)
    after = score(original, unrelated, *(article(index, content=REPORT, published_at=NOW,
                                                 cluster_membership_confidence=1)
                                         for index in range(3, 43)))
    assert after.cluster_confidence_score == before.cluster_confidence_score
    assert after.outlier_proportion == before.outlier_proportion
    assert after.temporal_coherence_score == before.temporal_coherence_score
    assert after.effective_report_weight == before.effective_report_weight == 2
    assert len(after.reports) == 2
    assert after.reports[0].article_ids == (1, *range(3, 43))


def test_duplicate_only_cluster_is_not_many_independent_coherence_checks():
    result = score(*(article(index, content=REPORT, cluster_membership_confidence=None) for index in range(1, 21)))
    assert len(result.reports) == 1
    assert result.reports[0].embedding_status == "no_peers"
    assert result.cluster_confidence_score == 0.5


def test_same_publisher_reports_share_one_unit_for_signal_and_outlier_fractions():
    result = score(*(article(index, publisher_key=" Publisher ", cluster_membership_confidence=1)
                     for index in range(1, 11)),
                   article(11, publisher_key="other", cluster_membership_confidence=0))
    assert result.effective_report_weight == 2
    assert result.membership_confidence_score == pytest.approx(0.5)
    assert result.outlier_proportion == pytest.approx(0.5)
    assert result.weakly_related_proportion == pytest.approx(0.5)
    assert result.reports[0].publisher_key == "publisher"


def test_publisher_weights_are_case_insensitive():
    result = score(article(1, publisher_key="p"), article(2, publisher_key=" P "), article(3))
    assert [report.weight for report in result.reports] == [0.5, 0.5, 1]
    assert result.effective_report_weight == 2


def test_temporal_coherence_measures_spread_around_event_center_instead_of_age():
    first = article(1, published_at=NOW - timedelta(hours=144))
    second = article(2, published_at=NOW)
    result = score(first, second)
    assert result.temporal_center_at == first.published_at
    assert result.mean_temporal_deviation_hours == 72
    assert result.temporal_coherence_score == 0.5
    assert result.cluster_confidence_score == pytest.approx(0.97 * 0.875)
    shifted = score(first.model_copy(update={"published_at": first.published_at - timedelta(days=100)}),
                    second.model_copy(update={"published_at": second.published_at - timedelta(days=100)}))
    assert shifted.cluster_confidence_score == result.cluster_confidence_score
    assert shifted.temporal_coherence_score == result.temporal_coherence_score


def test_temporal_median_and_deviation_are_publisher_balanced():
    result = score(*(article(index, publisher_key="p", published_at=NOW - timedelta(hours=72))
                     for index in range(1, 5)), article(5, published_at=NOW), article(6, published_at=NOW))
    assert result.temporal_center_at == NOW
    assert result.mean_temporal_deviation_hours == 24
    assert result.temporal_coherence_score == pytest.approx(2 ** (-1 / 3))


def test_temporal_penalty_and_half_life_are_configurable():
    reports = (article(1, published_at=NOW - timedelta(hours=48)), article(2, published_at=NOW))
    short = score(*reports, temporal_half_life_hours=12)
    long = score(*reports, temporal_half_life_hours=72)
    disabled = score(*reports, temporal_penalty=0)
    assert short.cluster_confidence_score < long.cluster_confidence_score < disabled.cluster_confidence_score
    assert disabled.cluster_confidence_score == pytest.approx(0.97)


def test_unknown_data_and_no_eligible_articles_are_distinct():
    unknown = score(article(embedding=(), cluster_membership_confidence=None))
    future = score(article(published_at=NOW + timedelta(hours=1)))
    assert unknown.cluster_confidence_score == 0.5 and unknown.basis == "fallback"
    assert future.cluster_confidence_score == future.gate_multiplier == 0
    assert future.basis == "unavailable"
    assert future.reports == ()
    assert future.temporal_center_at is future.mean_temporal_deviation_hours is None
    assert future.excluded_article_ids == (1,)


def test_future_publications_and_first_seen_observations_cannot_change_the_centroid():
    present = (article(2), article(3))
    result = score(*present, article(1, embedding=(0.0, 1.0),
                                    first_seen_at=NOW + timedelta(seconds=1)),
                   article(4, embedding=(-1.0, 0.0), published_at=NOW + timedelta(seconds=1)))
    assert result.reports == score(*present).reports
    assert result.cluster_confidence_score == score(*present).cluster_confidence_score
    assert result.excluded_article_ids == (1, 4)


def test_utc_elapsed_time_across_daylight_saving_is_consistent():
    local = ZoneInfo("Europe/Ljubljana")
    end = datetime(2026, 10, 25, 6, tzinfo=local)
    first = article(1, published_at=datetime(2026, 10, 25, 2, tzinfo=local, fold=0))
    second = article(2, published_at=datetime(2026, 10, 25, 2, tzinfo=local, fold=1))
    result = score(first, second, evaluated_at=end)
    assert result.mean_temporal_deviation_hours == 0.5
    assert result == score(first, second, evaluated_at=end.astimezone(timezone.utc))


def test_metadata_other_than_clustering_signals_does_not_grant_confidence():
    originals = (article(1), article(2))
    enriched = tuple(item.model_copy(update={
        "llm_rank": 10, "publisher_authority_score": 1, "originality_score": 1,
        "is_primary_source": True, "categories": ("sport",),
    }) for item in originals)
    changed = RankableCluster(cluster_id=7, articles=enriched, category="sport", created_at=NOW, changed_at=NOW)
    result = score_cluster_confidence(changed, NOW, CONFIG)
    assert result == score(*originals)


def test_input_order_is_deterministic_and_snapshots_and_results_are_immutable():
    reports = (article(1, content=REPORT), article(2, content=REPORT), article(3, content=UPDATE))
    cluster = RankableCluster(cluster_id=7, articles=reports)
    before = cluster.model_dump_json(), CONFIG.model_dump_json()
    result = score_cluster_confidence(cluster, NOW, CONFIG)
    assert all(score(*order) == result for order in permutations(reports))
    assert (cluster.model_dump_json(), CONFIG.model_dump_json()) == before
    with pytest.raises(ValidationError):
        result.cluster_confidence_score = 1
    with pytest.raises(ValidationError):
        result.reports[0].weight = 0.5


@pytest.mark.parametrize("confidence", [0.0, 0.1, 0.5, 0.9, 1.0])
def test_final_score_is_multiplicatively_gated_even_when_every_other_component_is_maximum(confidence):
    result = finalize_ranking(cluster_id=7, base_score=1, components=components(confidence),
                              evaluated_at=NOW, config=CONFIG)
    assert result.score == confidence ** 2
    assert result.score <= confidence
    assert result.components.cluster_confidence_score == confidence
    assert result.cluster_id == 7 and result.config_version == CONFIG.version


def test_a_large_bad_cluster_cannot_outrank_a_coherent_cluster_by_raising_its_base_score():
    coherent = score(article(1), article(2))
    bad = score(*(article(index, embedding=(1.0, 0.0) if index <= 20 else (0.0, 1.0))
                  for index in range(1, 41)))
    good_result = finalize_ranking(cluster_id=7, base_score=0.4,
                                   components=components(coherent.cluster_confidence_score), evaluated_at=NOW, config=CONFIG)
    bad_result = finalize_ranking(cluster_id=8, base_score=1.0,
                                  components=components(bad.cluster_confidence_score), evaluated_at=NOW, config=CONFIG)
    assert bad_result.score < good_result.score
    assert bad_result.score == bad.gate_multiplier


def test_gate_never_boosts_base_score_and_preserves_perfect_confidence():
    for base in (0.0, 0.1, 0.5, 1.0):
        for confidence in (0.0, 0.2, 0.5, 0.9, 1.0):
            assert 0 <= apply_confidence_gate(base, confidence, CONFIG) <= base
        assert apply_confidence_gate(base, 1, CONFIG) == base


def test_finalization_rejects_unbounded_article_totals_instead_of_allowing_gate_bypass():
    with pytest.raises(ValidationError):
        finalize_ranking(cluster_id=7, base_score=50, components=components(0.2),
                         evaluated_at=NOW, config=CONFIG)


def test_configured_gate_power_is_shared_by_scorer_and_finalization():
    result = score(article(1), article(2), gate_power=3)
    config = RankingConfig(version=CONFIG.version, parameters={"cluster_confidence": {"gate_power": 3}})
    final = finalize_ranking(cluster_id=7, base_score=0.8, components=components(result.cluster_confidence_score),
                             evaluated_at=NOW, config=config)
    assert final.score == 0.8 * result.gate_multiplier
    assert result.gate_multiplier == result.cluster_confidence_score ** 3


def test_finalization_keeps_component_explanations_and_normalizes_evaluation_time():
    supplied = components(0.5)
    result = finalize_ranking(cluster_id=7, base_score=0.8, components=supplied,
                              evaluated_at=NOW.astimezone(ZoneInfo("Europe/Ljubljana")), config=CONFIG)
    assert result.components == supplied
    assert result.evaluated_at == NOW
    assert result.model_dump(mode="json")["evaluated_at"] == "2026-09-13T12:00:00Z"
    assert result.score == 0.2


@pytest.mark.parametrize("invalid", [-0.1, 1.1, float("nan"), float("inf"), "0.5", True])
def test_gate_rejects_invalid_normalized_inputs(invalid):
    with pytest.raises(ValidationError):
        apply_confidence_gate(invalid, 0.5, CONFIG)
    with pytest.raises(ValidationError):
        apply_confidence_gate(0.5, invalid, CONFIG)


@pytest.mark.parametrize("parameters", [
    {"outlier_similarity": 0.8}, {"weak_similarity": 0.3}, {"strong_similarity": 0.7},
    {"outlier_similarity": -1.1}, {"strong_similarity": 1.1},
    {"outlier_membership": 0.6}, {"weak_membership": 0.1},
    {"outlier_membership": -0.1}, {"weak_membership": 1.1},
    {"semantic_weight": -0.1}, {"semantic_weight": 1.1},
    {"unknown_similarity_score": -0.1}, {"unknown_similarity_score": 1},
    {"unknown_membership_confidence": -0.1}, {"unknown_membership_confidence": 1},
    {"weak_relation_penalty": -0.1}, {"weak_relation_penalty": 1.1},
    {"temporal_half_life_hours": 0}, {"temporal_half_life_hours": -1},
    {"temporal_penalty": -0.1}, {"temporal_penalty": 1.1}, {"gate_power": 0.5}, {"typo": 1},
])
def test_invalid_policies_are_rejected(parameters):
    with pytest.raises(ValidationError):
        score(article(), **parameters)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
def test_nonfinite_configuration_is_rejected(value):
    for parameter in ClusterConfidenceConfig.model_fields:
        with pytest.raises(ValidationError):
            ClusterConfidenceConfig(**{parameter: value})


def test_naive_evaluation_time_is_rejected_by_scoring_and_finalization():
    with pytest.raises(ValueError, match="timezone"):
        score(article(), evaluated_at=NOW.replace(tzinfo=None))
    with pytest.raises(ValueError, match="timezone"):
        finalize_ranking(cluster_id=7, base_score=0.8, components=components(0.5),
                         evaluated_at=NOW.replace(tzinfo=None), config=CONFIG)

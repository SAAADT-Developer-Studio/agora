from datetime import datetime, timedelta, timezone
from itertools import permutations
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from app.ranking import (
    ClusterNewsworthiness, NewsworthinessConfig, NewsworthinessResult,
    RankableArticle, RankableCluster, RankingComponentScores, RankingConfig,
    normalize_llm_importance, score_newsworthiness,
)
from app.tests.ranking.samples import REPORT, UPDATE


NOW = datetime(2026, 9, 13, 12, tzinfo=timezone.utc)


def article(article_id=1, **overrides):
    values = dict(
        article_id=article_id, publisher_key=f"publisher-{article_id}",
        title="Event report", published_at=NOW - timedelta(hours=2), llm_rank=7,
        content=" ".join(f"report{article_id}word{index}" for index in range(70)),
    )
    values.update(overrides)
    return RankableArticle(**values)


def score(*articles, evaluated_at=NOW, newsworthiness=None, **parameters):
    return score_newsworthiness(
        RankableCluster(cluster_id=7, articles=articles, newsworthiness=newsworthiness), evaluated_at,
        RankingConfig(version="newsworthiness-test-v1", parameters={"newsworthiness": parameters}),
    )


def evaluation(value=0.8, **overrides):
    return ClusterNewsworthiness(score=value, evaluated_at=overrides.get("evaluated_at", NOW),
                                  version=overrides.get("version", "cluster-llm-v1"))


@pytest.mark.parametrize("rank", range(1, 11))
def test_llm_importance_normalizes_all_existing_ranks_in_the_correct_direction(rank):
    expected = (rank - 1) / 9
    assert normalize_llm_importance(rank) == expected
    assert score(article(llm_rank=rank)).semantic_importance_score == expected


@pytest.mark.parametrize("rank", [0, 11, -1, 5.5, 5.0, "5", True, False, float("nan"), float("inf")])
def test_invalid_llm_importance_is_rejected_instead_of_clamped(rank):
    with pytest.raises(ValueError, match="integer from 1 to 10"):
        normalize_llm_importance(rank)


def test_missing_importance_remains_distinct_from_the_lowest_known_rank():
    assert normalize_llm_importance(None) is None
    missing = score(article(llm_rank=None))
    lowest = score(article(llm_rank=1))
    assert missing.semantic_importance_score == 0.5
    assert missing.article_basis == "missing_scores"
    assert missing.source == "fallback"
    assert missing.selected_article_ids == ()
    assert missing.strongest_article_score is missing.top_reports_mean is None
    assert missing.reports[0].selection_reason == "missing_importance"
    assert lowest.semantic_importance_score == 0
    assert lowest.source == "article_ranks"
    assert lowest.selected_article_ids == (1,)


def test_default_formula_blends_strongest_with_top_three_publisher_reports():
    result = score(article(1, llm_rank=10), article(2, llm_rank=7), article(3, llm_rank=4),
                   article(4, llm_rank=1))
    assert result.selected_article_ids == (1, 2, 3)
    assert result.strongest_article_score == 1
    assert result.top_reports_mean == pytest.approx(2 / 3)
    assert result.article_newsworthiness_score == result.semantic_importance_score == pytest.approx(5 / 6)
    assert result.article_basis == "independent_reports"
    assert result.source == "article_ranks"
    assert result.reports[3].selection_reason == "outside_top_reports"
    assert result.cluster_evaluation_status == "absent"
    assert result.applied_cluster_weight == 0
    assert result.algorithm_version == "newsworthiness-v1"
    assert result.syndication_algorithm_version == "syndication-v1"
    assert result.config_version == "newsworthiness-test-v1"
    assert result.model_dump(mode="json")["evaluated_at"] == "2026-09-13T12:00:00Z"
    assert NewsworthinessResult.model_validate_json(result.model_dump_json()) == result


def test_mean_uses_only_available_reports_without_padding_with_missing_values():
    result = score(article(1, llm_rank=10), article(2, llm_rank=4), article(3, llm_rank=None))
    assert result.top_reports_mean == pytest.approx(2 / 3)
    assert result.semantic_importance_score == pytest.approx(5 / 6)
    assert result.selected_article_ids == (1, 2)


def test_report_volume_cannot_sum_its_way_to_higher_importance():
    for count in (1, 3, 25):
        result = score(*(article(index, llm_rank=4) for index in range(1, count + 1)))
        assert result.semantic_importance_score == pytest.approx(1 / 3)
        assert len(result.selected_article_ids) == min(count, 3)


def test_lower_scoring_reports_outside_top_set_do_not_dilute_the_result():
    top = (article(1, llm_rank=10), article(2, llm_rank=8), article(3, llm_rank=7))
    before = score(*top)
    after = score(*top, *(article(index, llm_rank=1) for index in range(4, 34)))
    assert after.semantic_importance_score == before.semantic_importance_score
    assert after.selected_article_ids == before.selected_article_ids


def test_new_stronger_independent_report_can_increase_newsworthiness():
    before = score(article(1, llm_rank=4), article(2, llm_rank=4), article(3, llm_rank=4))
    after = score(article(1, llm_rank=4), article(2, llm_rank=4), article(3, llm_rank=4),
                  article(4, llm_rank=10))
    assert after.semantic_importance_score > before.semantic_importance_score
    assert after.selected_article_ids == (4, 1, 2)


@pytest.mark.parametrize("copied_body", [REPORT, REPORT.upper(), REPORT.replace("spring", "summer")])
def test_high_scoring_copies_do_not_inflate_a_scored_family(copied_body):
    original = article(1, content=REPORT, llm_rank=4, published_at=NOW - timedelta(hours=4))
    other = article(2, content=UPDATE, llm_rank=7)
    result = score(original, other, article(3, content=copied_body, llm_rank=10, published_at=NOW))
    assert result.semantic_importance_score == score(original, other).semantic_importance_score
    assert result.selected_article_ids == (2, 1)
    family = result.reports[0]
    assert family.basis == "family_representative"
    assert family.article_ids == (1, 3)
    assert family.score_article_id == 1
    assert family.llm_rank == 4
    assert family.syndication_family_id == "7:1"
    assert not family.used_family_score_fallback


def test_many_copies_count_as_one_report_even_if_their_llm_judgments_disagree():
    original = article(1, llm_rank=7, content=REPORT, published_at=NOW - timedelta(hours=4))
    result = score(original, *(article(index, content=REPORT, llm_rank=10) for index in range(2, 42)))
    assert result.semantic_importance_score == score(original).semantic_importance_score
    assert len(result.reports) == 1
    assert result.selected_article_ids == (1,)
    assert len(result.reports[0].article_ids) == 41


def test_family_uses_first_scored_copy_only_when_representative_score_is_missing():
    original = article(1, content=REPORT, llm_rank=None, published_at=NOW - timedelta(hours=4))
    first_scored = article(2, content=REPORT, llm_rank=4)
    later_high = article(3, content=REPORT, llm_rank=10, published_at=NOW)
    result = score(original, first_scored, later_high)
    assert result.semantic_importance_score == pytest.approx(1 / 3)
    assert result.selected_article_ids == (2,)
    report = result.reports[0]
    assert report.used_family_score_fallback
    assert report.publisher_key == "publisher-1"
    assert report.representative_article_id == 1 and report.score_article_id == 2


def test_family_proxy_score_cannot_bypass_the_representative_publishers_limit():
    result = score(article(1, content=REPORT, llm_rank=None, publisher_key="p"),
                   article(2, content=REPORT, llm_rank=10),
                   article(3, content=UPDATE, llm_rank=7, publisher_key="p"))
    assert result.selected_article_ids == (2,)
    assert result.reports[1].selection_reason == "same_publisher"


def test_publisher_repetition_cannot_take_multiple_top_slots():
    base = (article(1, publisher_key=" Publisher ", llm_rank=10),
            article(2, llm_rank=4), article(3, llm_rank=4))
    result = score(*base, *(article(index, publisher_key="PUBLISHER", llm_rank=10)
                            for index in range(4, 24)))
    assert result.selected_article_ids == (1, 2, 3)
    assert result.semantic_importance_score == score(*base).semantic_importance_score
    assert all(report.selection_reason == "same_publisher" for report in result.reports[3:])


def test_publisher_can_replace_its_own_weaker_report_with_a_stronger_one():
    result = score(article(1, publisher_key="p", llm_rank=4),
                   article(2, publisher_key="p", llm_rank=10))
    assert result.selected_article_ids == (2,)
    assert result.semantic_importance_score == 1
    assert result.reports[0].selection_reason == "same_publisher"


def test_known_family_remains_semantically_valuable_when_original_publisher_is_absent():
    result = score(article(1, content=REPORT, llm_rank=7, is_syndicated=True),
                   article(2, content=REPORT, llm_rank=10, is_syndicated=True))
    assert result.semantic_importance_score == pytest.approx(2 / 3)
    assert result.article_basis == "independent_reports"
    assert len(result.reports) == 1


@pytest.mark.parametrize("content", [None, "Short report.", "subscribe now " * 100])
def test_unknown_content_can_supply_one_explicit_fallback_without_claiming_independence(content):
    result = score(article(1, content=content, llm_rank=7), article(2, content=content, llm_rank=4))
    assert result.article_basis == "unverified_report"
    assert result.selected_article_ids == (1,)
    assert result.semantic_importance_score == pytest.approx(2 / 3)
    assert all(report.basis == "unknown" for report in result.reports)


def test_unknown_and_unmatched_syndicated_scores_cannot_displace_verified_reporting():
    result = score(article(1, llm_rank=1), article(2, content=None, llm_rank=10),
                   article(3, is_syndicated=True, llm_rank=10))
    assert result.semantic_importance_score == 0
    assert result.selected_article_ids == (1,)
    assert result.reports[1].selection_reason == result.reports[2].selection_reason == "unverified_reporting"
    assert result.reports[2].basis == "unmatched_syndication"


def test_unmatched_syndication_can_supply_a_single_fallback_when_no_verified_score_exists():
    result = score(article(1, is_syndicated=True, llm_rank=7),
                   article(2, is_syndicated=True, llm_rank=4), article(3, llm_rank=None))
    assert result.article_basis == "unverified_report"
    assert result.selected_article_ids == (1,)
    assert result.semantic_importance_score == pytest.approx(2 / 3)


def test_unknown_flags_summaries_and_embeddings_do_not_establish_independent_reports():
    result = score(article(1, content=None, summary=REPORT, embedding=(1.0, 0.0), is_syndicated=False),
                   article(2, content=None, summary=UPDATE, embedding=(0.0, 1.0), is_syndicated=False))
    assert result.article_basis == "unverified_report"
    assert len(result.selected_article_ids) == 1


def test_missing_scores_are_ignored_instead_of_padded_with_neutral_per_article_scores():
    result = score(article(1, llm_rank=1), *(article(index, llm_rank=None) for index in range(2, 22)))
    assert result.semantic_importance_score == 0
    assert result.selected_article_ids == (1,)


def test_unknown_importance_fallback_is_configurable():
    assert score(article(llm_rank=None), unknown_importance=0.25).semantic_importance_score == 0.25


def test_future_publications_and_observations_are_excluded_before_family_detection():
    current = article(2, content=REPORT, llm_rank=4)
    result = score(current, article(1, content=REPORT, llm_rank=10,
                                    published_at=NOW - timedelta(hours=3), first_seen_at=NOW + timedelta(seconds=1)),
                   article(3, llm_rank=10, published_at=NOW + timedelta(seconds=1)))
    assert result.excluded_article_ids == (1, 3)
    assert result.reports == score(current).reports
    assert result.semantic_importance_score == score(current).semantic_importance_score


def test_no_eligible_articles_yields_zero_even_with_neutral_fallback_or_a_cluster_evaluation():
    result = score(article(published_at=NOW + timedelta(hours=1)), newsworthiness=evaluation())
    assert result.semantic_importance_score == result.article_newsworthiness_score == 0
    assert result.source == "unavailable"
    assert result.article_basis == "no_eligible_articles"
    assert result.cluster_evaluation_status == "no_eligible_articles"
    assert result.excluded_article_ids == (1,)


def test_importance_does_not_decay_with_age_or_change_with_generic_event_metadata():
    report = article(published_at=NOW - timedelta(days=30))
    original = RankableCluster(cluster_id=7, articles=(report,))
    changed_report = report.model_copy(update={
        "categories": ("sport",), "publisher_authority_score": 1.0,
        "originality_score": 1.0, "is_primary_source": True,
        "cluster_membership_confidence": 0.1,
    })
    changed = RankableCluster(cluster_id=7, articles=(changed_report,), category="sport",
                              created_at=NOW, changed_at=NOW)
    config = RankingConfig(version="test")
    assert score_newsworthiness(original, NOW, config) == score_newsworthiness(changed, NOW, config)
    assert score(report).semantic_importance_score == score(report, evaluated_at=NOW + timedelta(days=365)).semantic_importance_score


def test_order_ties_timezones_and_inputs_are_deterministic_and_immutable():
    reports = (article(1, content=REPORT), article(2, content=REPORT), article(3, content=UPDATE))
    original = RankableCluster(cluster_id=7, articles=reports)
    config = RankingConfig(version="test")
    before = original.model_dump_json(), config.model_dump_json()
    result = score_newsworthiness(original, NOW, config)
    for ordering in permutations(reports):
        assert score_newsworthiness(RankableCluster(cluster_id=7, articles=ordering), NOW, config) == result
    assert score_newsworthiness(original, NOW.astimezone(ZoneInfo("Europe/Ljubljana")), config) == result
    assert (original.model_dump_json(), config.model_dump_json()) == before
    with pytest.raises(ValidationError):
        result.semantic_importance_score = 0
    with pytest.raises(ValidationError):
        result.reports[0].selected = False


def test_first_seen_time_breaks_equal_score_and_publication_ties():
    result = score(article(1, first_seen_at=NOW), article(2, first_seen_at=NOW - timedelta(hours=1)),
                   top_reports=1)
    assert result.selected_article_ids == (2,)


@pytest.mark.parametrize("parameters", [{"top_reports": 1}, {"strongest_weight": 1}])
def test_strongest_only_policy_can_be_selected(parameters):
    result = score(article(1, llm_rank=10), article(2, llm_rank=1), **parameters)
    assert result.semantic_importance_score == 1


def test_mean_only_policy_can_be_selected():
    result = score(article(1, llm_rank=10), article(2, llm_rank=1), strongest_weight=0)
    assert result.semantic_importance_score == result.top_reports_mean == 0.5


@pytest.mark.parametrize("value", [0.0, 0.8, 1.0])
def test_precomputed_cluster_evaluation_replaces_article_aggregation_through_same_contract(value):
    result = score(article(llm_rank=4), newsworthiness=evaluation(value))
    assert result.semantic_importance_score == value
    assert result.article_newsworthiness_score == pytest.approx(1 / 3)
    assert result.source == "cluster_evaluation"
    assert result.cluster_evaluation_status == "used"
    assert result.cluster_evaluation_score == value
    assert result.cluster_evaluation_version == "cluster-llm-v1"
    assert result.applied_cluster_weight == 1
    components = RankingComponentScores(
        semantic_importance_score=result.semantic_importance_score, coverage_score=0.5,
        momentum_score=0.5, freshness_score=0.5, article_contribution_score=0.5,
        publisher_authority_score=0.5, cluster_confidence_score=0.5,
    )
    assert components.semantic_importance_score == value


def test_cluster_evaluation_can_supplement_article_aggregation_with_a_configurable_blend():
    result = score(article(llm_rank=1), newsworthiness=evaluation(0.8), cluster_score_weight=0.25)
    assert result.semantic_importance_score == 0.2
    assert result.source == "blended"
    assert result.applied_cluster_weight == 0.25


def test_missing_article_importance_does_not_dilute_an_available_cluster_evaluation():
    result = score(article(llm_rank=None), newsworthiness=evaluation(0.8), cluster_score_weight=0.25)
    assert result.semantic_importance_score == 0.8
    assert result.applied_cluster_weight == 1
    assert result.article_basis == "missing_scores"
    assert result.source == "cluster_evaluation"


def test_future_cluster_evaluation_is_ignored_until_available():
    available_at = NOW + timedelta(hours=1)
    judgment = evaluation(1.0, evaluated_at=available_at)
    before = score(article(llm_rank=1), newsworthiness=judgment)
    after = score(article(llm_rank=1), newsworthiness=judgment, evaluated_at=available_at)
    assert before.semantic_importance_score == 0
    assert before.cluster_evaluation_status == "future"
    assert before.cluster_evaluation_score is None
    assert after.semantic_importance_score == 1
    assert after.cluster_evaluation_status == "used"


def test_cluster_evaluation_can_be_disabled():
    result = score(article(llm_rank=1), newsworthiness=evaluation(1.0), cluster_score_weight=0)
    assert result.semantic_importance_score == 0
    assert result.source == "article_ranks"
    assert result.cluster_evaluation_status == "disabled"


@pytest.mark.parametrize("value", [-0.1, 1.1, float("nan"), float("inf"), "0.5", True])
def test_cluster_evaluation_rejects_invalid_prepared_values(value):
    with pytest.raises(ValidationError):
        evaluation(value)


def test_cluster_evaluation_requires_version_and_aware_availability_time():
    with pytest.raises(ValidationError):
        evaluation(version=" ")
    with pytest.raises(ValidationError):
        evaluation(evaluated_at=NOW.replace(tzinfo=None))
    snapshot = RankableCluster(cluster_id=7, articles=(article(),), newsworthiness=evaluation())
    assert RankableCluster.model_validate_json(snapshot.model_dump_json()) == snapshot
    with pytest.raises(ValidationError):
        snapshot.newsworthiness.score = 0


@pytest.mark.parametrize("parameter, value", [
    ("top_reports", 0), ("top_reports", -1), ("top_reports", 1.5), ("top_reports", True),
    ("strongest_weight", -0.1), ("strongest_weight", 1.1),
    ("unknown_importance", -0.1), ("unknown_importance", 1.1),
    ("cluster_score_weight", -0.1), ("cluster_score_weight", 1.1), ("typo", 1),
])
def test_invalid_configuration_is_rejected(parameter, value):
    with pytest.raises(ValidationError):
        score(article(), **{parameter: value})


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
def test_nonfinite_configuration_is_rejected(value):
    for parameter in NewsworthinessConfig.model_fields:
        with pytest.raises(ValidationError):
            NewsworthinessConfig(**{parameter: value})


def test_naive_evaluation_time_is_rejected():
    with pytest.raises(ValueError, match="timezone"):
        score(article(), evaluated_at=NOW.replace(tzinfo=None))

from datetime import datetime, timedelta, timezone
from itertools import permutations
from math import expm1, isfinite
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from app.ranking import (
    MomentumConfig, MomentumResult, RankableArticle, RankableCluster, RankingConfig,
    score_freshness, score_momentum,
)
from app.tests.ranking.samples import PARAPHRASE, REPORT, UPDATE


NOW = datetime(2026, 9, 13, 12, tzinfo=timezone.utc)


def article(article_id=1, hours_ago=1, **overrides):
    values = dict(
        article_id=article_id, publisher_key=f"publisher-{article_id}",
        title="Event report", published_at=NOW - timedelta(hours=hours_ago),
        content=" ".join(f"report{article_id}word{index}" for index in range(70)),
    )
    values.update(overrides)
    return RankableArticle(**values)


def score(*articles, evaluated_at=NOW, **parameters):
    return score_momentum(
        RankableCluster(cluster_id=7, articles=articles), evaluated_at,
        RankingConfig(version="momentum-test-v1", parameters={"momentum": parameters}),
    )


def test_first_independent_publisher_has_explainable_rates_and_versions():
    result = score(article())
    recent = result.recent_window
    assert result.previous_window.coverage_credit == 0
    assert recent.independent_article_count == recent.active_independent_publisher_count == 1
    assert recent.new_independent_publishers == ("publisher-1",)
    assert recent.new_independent_publisher_count == recent.effective_article_count == 1
    assert recent.coverage_credit == 1
    assert recent.velocity_per_hour == pytest.approx(1 / 6)
    assert result.velocity_change_per_hour == pytest.approx(1 / 6)
    assert result.acceleration_per_hour_squared == pytest.approx(1 / 36)
    assert result.relative_change == result.trend_multiplier == 1
    assert result.trend == "accelerating"
    assert result.momentum_score == result.activity_score == pytest.approx(-expm1(-1 / 3))
    decision = result.articles[0]
    assert decision.qualifies_as_coverage and decision.is_new_independent_publisher
    assert decision.reason == "new_independent_publisher"
    assert decision.publisher_window_ordinal == 1
    assert decision.article_credit == decision.new_publisher_credit == decision.coverage_credit == 1
    assert result.algorithm_version == "momentum-v1"
    assert result.article_contribution_algorithm_version == "article-contribution-v2"
    assert result.syndication_algorithm_version == "syndication-v1"
    assert result.config_version == "momentum-test-v1"
    assert result.model_dump(mode="json")["evaluated_at"] == "2026-09-13T12:00:00Z"
    assert MomentumResult.model_validate_json(result.model_dump_json()) == result


def test_recent_coverage_velocity_accelerates_and_slows_between_equal_windows():
    recent = [article(index) for index in range(20, 23)]
    rising = score(article(1, 8), *recent)
    steady = score(*(article(index, 8) for index in range(1, 4)), *recent)
    falling = score(*(article(index, 8) for index in range(1, 7)), *recent)
    assert rising.recent_window == steady.recent_window == falling.recent_window
    assert rising.trend == "accelerating"
    assert rising.relative_change == 0.5
    assert rising.acceleration_per_hour_squared == pytest.approx(2 / 36)
    assert steady.trend == "steady"
    assert steady.acceleration_per_hour_squared == steady.relative_change == 0
    assert steady.trend_multiplier == 0.8
    assert falling.trend == "slowing"
    assert falling.relative_change == pytest.approx(-1 / 3)
    assert falling.acceleration_per_hour_squared == pytest.approx(-3 / 36)
    assert rising.momentum_score > steady.momentum_score > falling.momentum_score > 0


def test_more_recent_independent_publishers_increase_velocity_with_diminishing_scores():
    results = [score(*(article(index) for index in range(1, count + 1)))
               for count in (1, 3, 20, 22)]
    assert [item.recent_window.coverage_credit for item in results] == [1, 3, 20, 22]
    scores = [item.momentum_score for item in results]
    assert all(0 < left < right <= 1 for left, right in zip(scores, scores[1:]))
    assert scores[1] - scores[0] > scores[3] - scores[2]


def test_no_recent_coverage_scores_zero_but_preserves_a_slowing_trend():
    result = score(article(1, 8))
    assert result.momentum_score == result.recent_window.velocity_per_hour == 0
    assert result.relative_change == -1
    assert result.acceleration_per_hour_squared < 0
    assert result.trend == "slowing"


def test_history_alone_is_inactive():
    result = score(article(1, 48))
    assert result.momentum_score == result.activity_score == 0
    assert result.relative_change == result.acceleration_per_hour_squared == 0
    assert result.trend == "inactive"
    assert result.articles[0].window == "history"
    assert result.articles[0].qualifies_as_coverage
    assert result.articles[0].coverage_credit == 0
    assert result.articles[0].publisher_window_ordinal is None


def test_old_history_prevents_counting_a_returning_publisher_as_new():
    old = article(1, 100, publisher_key=" Publisher ")
    update = article(2, publisher_key="PUBLISHER")
    result = score(old, update)
    assert result.recent_window.new_independent_publisher_count == 0
    assert result.recent_window.independent_article_count == 1
    assert result.recent_window.coverage_credit == 0.5
    assert result.articles[1].reason == "meaningful_report"
    assert result.articles[1].publisher_key == "publisher"
    assert not result.articles[1].is_new_independent_publisher


def test_new_publisher_can_broaden_coverage_without_refreshing_event_facts():
    old = article(1, 48, content=REPORT, embedding=(1.0, 0.0))
    recap = article(2, content=PARAPHRASE, embedding=(1.0, 0.0))
    result = score(old, recap)
    assert result.articles[1].novelty == pytest.approx(0.3)
    assert result.recent_window.new_independent_publisher_count == 1
    assert result.recent_window.coverage_credit == 1
    freshness = score_freshness(RankableCluster(cluster_id=7, articles=(old, recap)), NOW,
                                RankingConfig(version="test"))
    assert freshness.last_meaningful_update_at == old.published_at


def test_same_publisher_rewording_known_facts_creates_no_momentum():
    result = score(article(1, 48, content=REPORT, embedding=(1.0, 0.0)),
                   article(2, publisher_key="publisher-1", content=PARAPHRASE,
                           embedding=(1.0, 0.0)))
    assert result.articles[1].reason == "insufficient_novelty"
    assert result.recent_window.independent_article_count == result.momentum_score == 0


def test_repeated_novel_reports_share_a_small_bounded_allowance():
    reports = [article(index, publisher_key="publisher", hours_ago=5 - index / 100)
               for index in range(1, 41)]
    result = score(*reports)
    assert result.recent_window.independent_article_count == 40
    assert result.recent_window.new_independent_publisher_count == 1
    assert result.recent_window.active_independent_publisher_count == 1
    assert result.recent_window.effective_article_count <= 1.15
    assert result.recent_window.coverage_credit <= 1.075
    assert result.articles[1].article_credit == 0.075
    assert result.articles[2].article_credit == 0.0375
    assert score(reports[0]).momentum_score < result.momentum_score < score(article(1), article(2)).momentum_score


def test_repeat_allowance_resets_per_window_without_renewing_new_publisher_credit():
    result = score(article(1, 48, publisher_key="p"), article(2, 9, publisher_key="p"),
                   article(3, 8, publisher_key="p"), article(4, 3, publisher_key="p"),
                   article(5, 2, publisher_key="p"))
    assert result.previous_window.coverage_credit == result.recent_window.coverage_credit
    assert result.previous_window.effective_article_count == 1.075
    assert result.recent_window.new_independent_publisher_count == 0
    assert [item.publisher_window_ordinal for item in result.articles] == [None, 1, 2, 1, 2]
    assert result.trend == "steady"


@pytest.mark.parametrize("content", [REPORT, REPORT.upper(), REPORT.replace("spring", "summer")])
def test_copied_old_reporting_creates_no_current_momentum(content):
    old = article(1, 48, content=REPORT)
    result = score(old, article(2, content=content, summary=UPDATE, embedding=(0.0, 1.0)))
    assert result.momentum_score == score(old).momentum_score == 0
    assert result.articles[1].reason == "syndicated_copy"
    assert result.articles[1].coverage_credit == 0


def test_many_new_publisher_copies_leave_both_windows_and_score_unchanged():
    original = article(1, 8, content=REPORT)
    update = article(2, 3, content=UPDATE)
    baseline = score(original, update)
    result = score(original, update, *(article(index, content=UPDATE) for index in range(3, 43)))
    assert result.momentum_score == baseline.momentum_score
    assert result.previous_window.coverage_credit == baseline.previous_window.coverage_credit
    assert result.recent_window.coverage_credit == baseline.recent_window.coverage_credit == 1
    assert result.recent_window.new_independent_publishers == ("publisher-2",)
    assert result.articles[1].reason == "new_independent_publisher"  # Family representative counts once.
    assert all(item.reason == "syndicated_copy" for item in result.articles[2:])


def test_same_publisher_copies_do_not_consume_the_novel_reporting_allowance():
    result = score(article(1, 4, publisher_key="p", content=REPORT),
                   article(2, 3, publisher_key="p", content=REPORT),
                   article(3, 2, publisher_key="p", content=UPDATE))
    assert result.articles[1].publisher_window_ordinal is None
    assert result.articles[2].publisher_window_ordinal == 2
    assert result.articles[2].article_credit == 0.075


def test_an_explicitly_syndicated_family_representative_cannot_generate_momentum():
    result = score(article(1, 3, content=REPORT, is_syndicated=True), article(2, content=REPORT))
    assert result.momentum_score == 0
    assert all(item.reason == "syndicated_copy" for item in result.articles)


def test_explicit_syndication_blocks_an_otherwise_independent_body():
    result = score(article(is_syndicated=True, originality_score=1.0, is_primary_source=True))
    assert result.momentum_score == 0
    assert result.articles[0].reason == "syndicated_copy"


@pytest.mark.parametrize("content", [None, "Very short report.", "subscribe today " * 100])
def test_missing_or_insufficient_body_gets_no_credit_even_with_other_signals(content):
    result = score(article(content=content, summary=UPDATE, embedding=(1.0, 0.0),
                           is_syndicated=False, originality_score=1.0,
                           publisher_authority_score=1.0, is_primary_source=True))
    assert result.momentum_score == 0
    assert result.articles[0].reason == "insufficient_content"
    assert not result.articles[0].is_new_independent_publisher


@pytest.mark.parametrize("prior_kind", ["unknown", "copy"])
def test_earlier_unknown_or_copied_post_does_not_spend_a_publishers_first_independent_credit(prior_kind):
    old = article(1, 48, publisher_key="p", content=None if prior_kind == "unknown" else REPORT,
                  is_syndicated=True if prior_kind == "copy" else None)
    result = score(old, article(2, publisher_key="p", content=UPDATE))
    assert result.articles[1].reason == "new_independent_publisher"
    assert result.recent_window.new_independent_publishers == ("p",)
    assert result.recent_window.coverage_credit == 1


@pytest.mark.parametrize("publisher", ["publisher-1", "new-publisher"])
def test_compilations_of_known_reports_create_no_momentum_despite_different_embeddings(publisher):
    result = score(article(1, 48, content=REPORT, embedding=(1.0, 0.0)),
                   article(2, 24, content=UPDATE, embedding=(0.0, 1.0)),
                   article(3, publisher_key=publisher, content=REPORT + " " + UPDATE,
                           embedding=(-1.0, -1.0)))
    assert result.articles[2].novelty > 0.5
    assert result.articles[2].new_text_fraction < 0.2
    assert result.articles[2].reason == "insufficient_new_text"
    assert result.momentum_score == 0


def test_windows_have_nonoverlapping_open_starts_and_closed_ends():
    result = score(article(1, 12), article(2, published_at=NOW - timedelta(hours=12) + timedelta(microseconds=1)),
                   article(3, 6), article(4, published_at=NOW - timedelta(hours=6) + timedelta(microseconds=1)),
                   article(5, 0))
    assert result.previous_window.start_at == NOW - timedelta(hours=12)
    assert result.previous_window.end_at == result.recent_window.start_at == NOW - timedelta(hours=6)
    assert result.recent_window.end_at == NOW
    assert result.previous_window.article_ids == (2, 3)
    assert result.recent_window.article_ids == (4, 5)
    assert result.articles[0].window == "history"
    assert result.trend == "steady"


def test_future_publications_and_future_first_seen_are_excluded_before_comparison():
    current = article(2, content=REPORT)
    result = score(current, article(1, 10, content=REPORT, first_seen_at=NOW + timedelta(seconds=1)),
                   article(3, published_at=NOW + timedelta(seconds=1), content=REPORT))
    assert result.excluded_article_ids == (1, 3)
    assert result.articles == score(current).articles
    assert result.momentum_score == score(current).momentum_score


def test_all_future_articles_are_inactive():
    result = score(article(hours_ago=-1))
    assert result.momentum_score == 0
    assert result.articles == ()
    assert result.excluded_article_ids == (1,)
    assert result.trend == "inactive"


def test_ingesting_an_old_report_now_does_not_create_recent_velocity():
    result = score(article(1, 48, first_seen_at=NOW))
    assert result.momentum_score == 0
    assert result.articles[0].window == "history"


def test_window_size_changes_rates_and_acceleration_in_hours():
    result = score(article(1, 4), article(2, 2), article(3, 1), window_hours=3)
    assert result.previous_window.velocity_per_hour == pytest.approx(1 / 3)
    assert result.recent_window.velocity_per_hour == pytest.approx(2 / 3)
    assert result.acceleration_per_hour_squared == pytest.approx(1 / 9)


def test_utc_windows_cross_daylight_saving_using_elapsed_time():
    local_now = datetime(2026, 10, 25, 6, tzinfo=ZoneInfo("Europe/Ljubljana"))
    utc_now = local_now.astimezone(timezone.utc)
    report = article(published_at=utc_now - timedelta(hours=6))
    result = score(report, evaluated_at=local_now)
    assert result == score(report, evaluated_at=utc_now)
    assert result.recent_window.start_at == utc_now - timedelta(hours=6)
    assert result.previous_window.article_ids == (1,)


def test_article_order_and_ties_are_deterministic_without_mutating_inputs():
    reports = (article(1, content=REPORT), article(2, content=REPORT), article(3, content=UPDATE))
    before = tuple(item.model_dump_json() for item in reports)
    result = score(*reports)
    assert all(score(*ordering) == result for ordering in permutations(reports))
    assert tuple(item.model_dump_json() for item in reports) == before
    assert result.articles[0].qualifies_as_coverage
    assert result.articles[1].reason == "syndicated_copy"
    with pytest.raises(ValidationError):
        result.momentum_score = 1
    with pytest.raises(ValidationError):
        result.recent_window.coverage_credit = 99


def test_category_authority_article_rank_and_generic_timestamps_do_not_boost_momentum():
    original = article()
    enriched = original.model_copy(update={
        "categories": ("sport",), "publisher_authority_score": 1.0,
        "llm_rank": 10, "is_primary_source": True, "originality_score": 1.0,
    })
    cluster = RankableCluster(cluster_id=7, articles=(enriched,), category="sport",
                              created_at=NOW, changed_at=NOW)
    result = score_momentum(cluster, NOW, RankingConfig(version="momentum-test-v1"))
    assert result == score(original)


def test_component_uses_novelty_policy_without_using_final_article_contribution_weights():
    reports = (article(1, 48), article(2, publisher_key="publisher-1"))
    result = score_momentum(RankableCluster(cluster_id=7, articles=reports), NOW, RankingConfig(
        version="momentum-test-v1", parameters={"article_contribution": {
            "publisher_repeat_decay": 0.01, "freshness_half_life_hours": 0.01,
            "authority_weight": 1.0, "normalization_scale": 100.0,
        }},
    ))
    assert result == score(*reports)


def test_repeat_credit_can_be_disabled_without_losing_first_meaningful_report():
    result = score(article(1, 2, publisher_key="p"), article(2, publisher_key="p"), publisher_repeat_credit=0)
    assert result.recent_window.effective_article_count == 1
    assert result.articles[1].qualifies_as_coverage
    assert result.articles[1].article_credit == 0


def test_acceleration_weight_can_be_disabled():
    current = article(10)
    rising = score(current, acceleration_weight=0)
    falling = score(article(1, 8), article(2, 8), current, acceleration_weight=0)
    assert rising.momentum_score == falling.momentum_score == rising.activity_score
    assert rising.trend == "accelerating" and falling.trend == "slowing"


def test_novelty_threshold_is_configurable_for_returning_publishers():
    old = article(1, 48, content=REPORT, embedding=(1.0, 0.0))
    recap = article(2, publisher_key="publisher-1", content=PARAPHRASE, embedding=(1.0, 0.0))
    assert score(old, recap).momentum_score == 0
    relaxed = score(old, recap, minimum_novelty=0.25)
    assert relaxed.articles[1].reason == "meaningful_report"
    assert relaxed.recent_window.coverage_credit == 0.5


@pytest.mark.parametrize("publisher_weight, expected_credit", [(0, 1.0), (0.5, 0.5), (1, 0.0)])
def test_publisher_and_article_weights_control_returning_report_credit(publisher_weight, expected_credit):
    result = score(article(1, 48), article(2, publisher_key="publisher-1"),
                   new_publisher_weight=publisher_weight)
    assert result.recent_window.independent_article_count == 1
    assert result.recent_window.new_independent_publisher_count == 0
    assert result.recent_window.coverage_credit == expected_credit


@pytest.mark.parametrize("parameter, value", [
    ("window_hours", 0), ("window_hours", -1), ("window_hours", 1e-12), ("window_hours", 8761),
    ("new_publisher_weight", -0.1), ("new_publisher_weight", 1.1),
    ("publisher_repeat_credit", -0.1), ("publisher_repeat_credit", 1),
    ("publisher_repeat_decay", 0), ("publisher_repeat_decay", 1),
    ("minimum_novelty", 0), ("minimum_novelty", 1.1),
    ("minimum_new_text_fraction", 0), ("minimum_new_text_fraction", 1.1),
    ("velocity_scale_per_hour", 0), ("velocity_scale_per_hour", -1),
    ("acceleration_weight", -0.1), ("acceleration_weight", 1.1), ("typo", 1),
])
def test_invalid_momentum_parameters_are_rejected(parameter, value):
    with pytest.raises(ValidationError):
        score(article(), **{parameter: value})


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
def test_nonfinite_parameters_are_rejected(value):
    for parameter in MomentumConfig.model_fields:
        with pytest.raises(ValidationError):
            MomentumConfig(**{parameter: value})


def test_naive_evaluation_time_is_rejected():
    with pytest.raises(ValueError, match="timezone"):
        score(article(), evaluated_at=NOW.replace(tzinfo=None))


def test_datetime_range_failure_has_an_explicit_error():
    with pytest.raises(ValueError, match="momentum windows"):
        score(article(), evaluated_at=datetime(1, 1, 1, tzinfo=timezone.utc))


@pytest.mark.parametrize("scale", [5e-324, 1e308])
def test_extreme_positive_normalization_scales_keep_scores_finite(scale):
    result = score(article(), velocity_scale_per_hour=scale)
    assert isfinite(result.momentum_score)
    assert 0 <= result.momentum_score <= 1

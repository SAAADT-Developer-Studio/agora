from datetime import datetime, timedelta, timezone
from itertools import permutations
from math import isfinite

import pytest
from pydantic import ValidationError

from app.ranking import RankableArticle, RankableCluster, RankingConfig, score_coverage
from app.tests.ranking.samples import PARAPHRASE, REPORT, UPDATE


NOW = datetime(2026, 9, 13, 12, tzinfo=timezone.utc)


def article(article_id=1, **overrides):
    values = dict(article_id=article_id, publisher_key=f"publisher-{article_id:03d}",
                  title="Event report", content=REPORT, published_at=NOW)
    values.update(overrides)
    return RankableArticle(**values)


def independent_articles(count):
    return tuple(article(index, content=" ".join(f"report{index}word{n}" for n in range(70)))
                 for index in range(1, count + 1))


def score(*articles, evaluated_at=NOW, **parameters):
    return score_coverage(
        RankableCluster(cluster_id=7, articles=articles), evaluated_at,
        RankingConfig(version="coverage-test-v1", parameters={"coverage": parameters}),
    )


def weights(result):
    return {publisher.publisher_key: publisher.coverage_weight for publisher in result.publishers}


def test_independent_publishers_receive_one_unit_each_with_explainable_output():
    result = score(article(1), article(2, content=UPDATE), article(3, content=PARAPHRASE))
    assert result.distinct_publisher_count == 3
    assert result.effective_publisher_count == 3.0
    assert result.coverage_score == pytest.approx(0.4511883639)
    assert all(publisher.basis == "independent" for publisher in result.publishers)
    assert all(publisher.coverage_weight == 1.0 for publisher in result.publishers)
    assert result.syndicated_families == ()
    assert result.config_version == "coverage-test-v1"
    assert result.algorithm_version == "coverage-v1"
    assert result.syndication_algorithm_version == "syndication-v1"
    assert result.model_dump(mode="json")["evaluated_at"] == "2026-09-13T12:00:00Z"


def test_one_to_three_independent_publishers_matters_more_than_twenty_to_twenty_two():
    scores = {count: score(*independent_articles(count)).coverage_score for count in (1, 3, 20, 22)}
    assert scores[1] < scores[3] < scores[20] < scores[22] < 1.0
    assert scores[3] - scores[1] > 40 * (scores[22] - scores[20])


def test_every_additional_independent_publisher_has_a_smaller_increment():
    previous, previous_gain = 0.0, 1.0
    for count in range(1, 23):
        current = score(*independent_articles(count)).coverage_score
        gain = current - previous
        assert 0 < gain < previous_gain
        previous, previous_gain = current, gain


def test_many_distinct_reports_from_one_publisher_do_not_increase_coverage():
    many = tuple(report.model_copy(update={"publisher_key": "publisher"})
                 for report in independent_articles(30))
    one = score(many[0])
    result = score(*many)
    assert result.distinct_publisher_count == result.effective_publisher_count == 1
    assert result.coverage_score == one.coverage_score
    assert result.publishers[0].article_ids == tuple(range(1, 31))


def test_duplicate_records_from_existing_publishers_do_not_change_coverage():
    original = (article(1), article(2, content=UPDATE), article(3, content=PARAPHRASE))
    copies = tuple(report.model_copy(update={"article_id": 10 * n + index})
                   for n in range(1, 11) for index, report in enumerate(original, 1))
    before, after = score(*original), score(*original, *copies)
    assert after.distinct_publisher_count == before.distinct_publisher_count == 3
    assert after.effective_publisher_count == before.effective_publisher_count == 3
    assert after.coverage_score == before.coverage_score
    assert weights(after) == weights(before)


def test_case_and_surrounding_whitespace_do_not_create_extra_publishers():
    result = score(article(1, publisher_key=" Publisher "),
                   article(2, publisher_key="PUBLISHER", content=UPDATE))
    assert result.distinct_publisher_count == 1
    assert weights(result) == {"publisher": 1.0}


def test_four_syndicated_publishers_count_as_about_one_independent_publisher():
    copies = score(*(article(index) for index in range(1, 5)))
    independent = score(*independent_articles(4))
    assert copies.distinct_publisher_count == independent.distinct_publisher_count == 4
    assert copies.effective_publisher_count == pytest.approx(1.13125)
    assert weights(copies) == pytest.approx({
        "publisher-001": 1.0, "publisher-002": 0.075,
        "publisher-003": 0.0375, "publisher-004": 0.01875,
    })
    assert copies.coverage_score < independent.coverage_score
    assert copies.publishers[0].basis == "family_representative"
    assert copies.publishers[1].basis == "syndicated"
    assert all(publisher.syndication_family_ids == ("7:1",) for publisher in copies.publishers)


def test_many_syndicated_publishers_cannot_exhaust_the_coverage_scale():
    result = score(*(article(index) for index in range(1, 101)))
    assert result.distinct_publisher_count == 100
    assert result.effective_publisher_count <= 1.15
    assert result.coverage_score < score(*independent_articles(2)).coverage_score


def test_repeated_copies_from_one_publisher_do_not_consume_extra_family_allowance():
    before = score(article(1), article(3), article(5))
    after = score(article(1), article(2, publisher_key="publisher-001"),
                  article(3), article(4, publisher_key="PUBLISHER-003"), article(5))
    assert weights(after) == weights(before)
    assert after.effective_publisher_count == before.effective_publisher_count


def test_a_publisher_receives_its_best_family_allowance_without_summing_families():
    result = score(article(1, publisher_key="source"), article(2, publisher_key="copy"),
                   article(3, publisher_key="source", content=UPDATE),
                   article(4, publisher_key="copy", content=UPDATE))
    assert len(result.syndicated_families) == 2
    assert weights(result) == pytest.approx({"source": 1.0, "copy": 0.075})
    assert result.effective_publisher_count == pytest.approx(1.075)


def test_distinct_original_publishers_and_families_receive_separate_credit():
    result = score(article(1), article(2), article(3, content=UPDATE), article(4, content=UPDATE))
    assert len(result.syndicated_families) == 2
    assert result.effective_publisher_count == pytest.approx(2.15)


def test_independent_writing_upgrades_a_syndicated_publisher_once():
    syndicated = score(article(1), article(2))
    upgraded = score(article(1), article(2), article(3, publisher_key="publisher-002", content=UPDATE))
    assert weights(syndicated)["publisher-002"] == 0.075
    assert weights(upgraded)["publisher-002"] == 1.0
    assert upgraded.effective_publisher_count == 2.0
    assert upgraded.publishers[1].basis == "independent"


def test_an_already_independent_publisher_gets_no_copy_credit_and_uses_no_allowance():
    result = score(article(1), article(2), article(3),
                   article(4, publisher_key="publisher-002", content=UPDATE))
    assert weights(result) == pytest.approx({
        "publisher-001": 1.0, "publisher-002": 1.0, "publisher-003": 0.075,
    })


@pytest.mark.parametrize("content", [None, "short text", "subscribe now " * 50])
def test_unknown_body_receives_partial_credit_even_with_a_claimed_independent_flag(content):
    result = score(article(content=content, is_syndicated=False, originality_score=1.0,
                           summary=REPORT, embedding=(1.0, 0.0)))
    publisher, = result.publishers
    assert publisher.basis == "unknown"
    assert publisher.coverage_weight == result.effective_publisher_count == 0.5
    assert result.coverage_score < score(article()).coverage_score


def test_multiple_unknown_reports_do_not_accumulate_for_one_publisher():
    result = score(*(article(index, publisher_key="publisher", content=None) for index in range(1, 21)))
    assert result.distinct_publisher_count == 1
    assert result.effective_publisher_count == 0.5


def test_unknown_reports_cannot_raise_a_known_syndicated_publishers_weight():
    before = score(article(1), article(2))
    after = score(article(1), article(2),
                  article(3, publisher_key="publisher-002", content=None))
    assert weights(after) == weights(before)
    assert after.coverage_score == before.coverage_score
    assert after.publishers[1].basis == "syndicated"


@pytest.mark.parametrize("body", [None, REPORT])
def test_explicit_syndication_without_a_matching_family_is_discounted(body):
    result = score(article(content=body, is_syndicated=True))
    assert result.publishers[0].basis == "syndicated"
    assert result.effective_publisher_count == 0.15
    assert result.syndicated_families == ()


def test_explicitly_flagged_family_still_counts_its_writing_once():
    result = score(article(1, is_syndicated=True), article(2, is_syndicated=True))
    assert result.effective_publisher_count == pytest.approx(1.075)
    assert result.publishers[0].basis == "family_representative"


def test_false_syndication_flags_and_high_originality_cannot_override_detected_copies():
    result = score(article(1), article(2, is_syndicated=False, originality_score=1.0))
    assert result.publishers[1].coverage_weight == 0.075
    assert result.publishers[1].basis == "syndicated"


def test_coverage_is_independent_of_authority_freshness_and_other_article_score_factors():
    plain = article(published_at=NOW - timedelta(days=10))
    changed = article(publisher_authority_score=1.0, is_primary_source=True, llm_rank=10,
                      originality_score=0.0, cluster_membership_confidence=0.0,
                      summary=REPORT, embedding=(1.0, 0.0), categories=("transport",))
    assert score(plain).coverage_score == score(changed).coverage_score
    assert score(changed, evaluated_at=NOW + timedelta(days=10)).coverage_score == score(changed).coverage_score


def test_evaluation_filters_future_reports_before_counting_publishers_and_families():
    result = score(article(1), article(2, published_at=NOW + timedelta(seconds=1)),
                   article(3, published_at=NOW - timedelta(days=1),
                           first_seen_at=NOW + timedelta(seconds=1)))
    assert result.excluded_article_ids == (2, 3)
    assert result.distinct_publisher_count == result.effective_publisher_count == 1
    assert result.syndicated_families == ()
    assert result.publishers[0].basis == "independent"


def test_no_eligible_articles_means_zero_coverage():
    result = score(article(published_at=NOW + timedelta(days=1)))
    assert result.publishers == result.syndicated_families == ()
    assert result.distinct_publisher_count == result.effective_publisher_count == result.coverage_score == 0


def test_input_order_does_not_affect_coverage_or_diagnostics():
    reports = (article(1), article(2), article(3, content=UPDATE), article(4, content=None))
    expected = score(*reports)
    for ordering in permutations(reports):
        assert score(*ordering) == expected


def test_equivalent_timezones_and_repeated_calls_produce_identical_results():
    local = timezone(timedelta(hours=2))
    assert score(article()) == score(article(published_at=NOW.astimezone(local)),
                                     evaluated_at=NOW.astimezone(local))
    assert score(article()) == score(article())


def test_inputs_are_unchanged_and_unrelated_component_settings_are_ignored():
    cluster = RankableCluster(cluster_id=7, articles=(article(1), article(2)))
    config = RankingConfig(version="custom-v1", parameters={"article_contribution": {"authority_weight": 0}})
    before = cluster.model_dump(), config.model_dump()
    result = score_coverage(cluster, NOW, config)
    assert (cluster.model_dump(), config.model_dump()) == before
    assert result.config_version == "custom-v1"
    assert result.coverage_score == score(*cluster.articles).coverage_score
    with pytest.raises(ValidationError, match="frozen"):
        result.coverage_score = 0.0


def test_coverage_uses_configured_syndication_detection():
    cluster = RankableCluster(cluster_id=7, articles=(article(1), article(2, content=REPORT.replace("spring", "summer"))))
    config = RankingConfig(version="strict-v1", parameters={"syndication": {"similarity_threshold": 1.0}})
    assert score_coverage(cluster, NOW, config).effective_publisher_count == 2.0
    assert score(*cluster.articles).effective_publisher_count == pytest.approx(1.075)


def test_coverage_weights_family_allowance_and_normalization_are_configurable():
    assert score(article(content=None), unknown_publisher_weight=0.4).effective_publisher_count == 0.4
    assert score(article(is_syndicated=True), syndicated_publisher_weight=0.1).effective_publisher_count == 0.1
    assert score(article(1), article(2), family_distribution_credit=0).effective_publisher_count == 1
    assert score(article(1), article(2), family_distribution_decay=0.8).effective_publisher_count == pytest.approx(1.03)
    assert score(article(1), article(2), syndicated_publisher_weight=0.01).effective_publisher_count == pytest.approx(1.01)
    assert score(article(), normalization_scale=2).coverage_score > score(article()).coverage_score


@pytest.mark.parametrize("scale", [1e-308, 1e308])
def test_extreme_valid_scales_keep_scores_finite_and_bounded(scale):
    result = score(*independent_articles(3), normalization_scale=scale)
    assert isfinite(result.coverage_score)
    assert 0.0 <= result.coverage_score <= 1.0


@pytest.mark.parametrize("parameters", [
    {"normalization_scale": 0}, {"normalization_scale": -1},
    {"normalization_scale": float("inf")}, {"normalization_scale": float("nan")},
    {"unknown_publisher_weight": 1}, {"unknown_publisher_weight": -0.1},
    {"unknown_publisher_weight": 0.1}, {"syndicated_publisher_weight": 1},
    {"syndicated_publisher_weight": -0.1}, {"family_distribution_credit": -0.1},
    {"family_distribution_credit": 1}, {"family_distribution_decay": 0},
    {"family_distribution_decay": 1}, {"typo": 0.5},
])
def test_invalid_coverage_policy_is_rejected(parameters):
    with pytest.raises(ValidationError):
        score(article(), **parameters)


def test_naive_evaluation_time_is_rejected():
    with pytest.raises(ValueError, match="timezone"):
        score(article(), evaluated_at=NOW.replace(tzinfo=None))

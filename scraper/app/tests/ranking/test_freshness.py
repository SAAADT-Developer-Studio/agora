from datetime import datetime, timedelta, timezone
from itertools import permutations
from math import isfinite
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from app.ranking import (
    FreshnessConfig, RankableArticle, RankableCluster, RankingConfig,
    score_article_contribution, score_coverage, score_freshness, score_publisher_authority,
)
from app.tests.ranking.samples import PARAPHRASE, REPORT, UPDATE


NOW = datetime(2026, 9, 13, 12, tzinfo=timezone.utc)
OLD = NOW - timedelta(days=2)


def article(article_id=1, **overrides):
    values = dict(article_id=article_id, publisher_key=f"publisher-{article_id}",
                  title="Event report", content=REPORT, summary=REPORT,
                  embedding=(1.0, 0.0), published_at=OLD)
    values.update(overrides)
    return RankableArticle(**values)


def score(*articles, category=None, created_at=None, changed_at=None, evaluated_at=NOW, **parameters):
    return score_freshness(
        RankableCluster(cluster_id=7, articles=articles, category=category,
                        created_at=created_at, changed_at=changed_at),
        evaluated_at,
        RankingConfig(version="freshness-test-v1", parameters={"freshness": parameters}),
    )


def test_initial_report_establishes_the_event_clock_with_explainable_output():
    result = score(article())
    assert result.last_meaningful_update_at == result.decay_started_at == OLD
    assert result.latest_meaningful_article_id == 1
    assert result.anchor_basis == "initial_report"
    assert result.age_hours == 48
    assert result.freshness_score == 0.25
    assert result.articles[0].qualifies_as_development
    assert result.algorithm_version == "freshness-v1"
    assert result.article_contribution_algorithm_version == "article-contribution-v2"
    assert result.syndication_algorithm_version == "syndication-v1"
    assert result.config_version == "freshness-test-v1"
    assert result.model_dump(mode="json")["evaluated_at"] == "2026-09-13T12:00:00Z"


def test_decay_halves_every_half_life_and_is_monotone_without_a_development():
    report = article(published_at=NOW)
    scores = [score(report, evaluated_at=NOW + timedelta(hours=hours)).freshness_score
              for hours in (0, 12, 24, 48, 72)]
    assert scores == pytest.approx([1, 2 ** -0.5, 0.5, 0.25, 0.125])
    assert all(earlier > later for earlier, later in zip(scores, scores[1:]))


def test_a_meaningful_development_refreshes_from_its_publication_time():
    update_time = NOW - timedelta(hours=6)
    update = article(2, content=UPDATE, summary=UPDATE, embedding=(0.0, 1.0), published_at=update_time)
    result = score(article(1), update)
    assert result.last_meaningful_update_at == result.decay_started_at == update_time
    assert result.latest_meaningful_article_id == 2
    assert result.anchor_basis == "meaningful_development"
    assert result.age_hours == 6
    assert result.freshness_score == pytest.approx(2 ** (-6 / 24))


@pytest.mark.parametrize("copy", [REPORT, REPORT.upper(), REPORT.replace("spring", "summer")])
def test_new_exact_and_lightly_edited_copies_do_not_refresh_an_old_event(copy):
    before = score(article(1))
    after = score(article(1), article(2, content=copy, published_at=NOW,
                                     first_seen_at=NOW, embedding=(0.0, 1.0)))
    assert after.freshness_score == before.freshness_score
    assert after.last_meaningful_update_at == OLD
    assert after.articles[1].reason == "syndicated_copy"
    assert not after.articles[1].qualifies_as_development


def test_many_copies_and_a_recent_cluster_changed_timestamp_do_not_refresh_the_event():
    result = score(article(1), *(article(index, published_at=NOW) for index in range(2, 41)), changed_at=NOW)
    assert result.freshness_score == score(article()).freshness_score == 0.25
    assert result.latest_meaningful_article_id == 1
    assert sum(item.qualifies_as_development for item in result.articles) == 1


def test_copies_of_a_real_development_keep_that_developments_time():
    update_time = NOW - timedelta(hours=8)
    result = score(article(1), article(2, content=UPDATE, summary=UPDATE, embedding=(0.0, 1.0),
                                      published_at=update_time),
                   article(3, content=UPDATE, summary=UPDATE, embedding=(0.0, 1.0), published_at=NOW))
    assert result.last_meaningful_update_at == update_time
    assert result.latest_meaningful_article_id == 2
    assert result.articles[2].reason == "syndicated_copy"


def test_new_publisher_and_new_wording_of_the_same_facts_do_not_refresh_with_matching_embeddings():
    result = score(article(1), article(2, content=PARAPHRASE, summary=PARAPHRASE, published_at=NOW))
    assert result.articles[1].new_text_fraction == 1.0
    assert result.articles[1].novelty == pytest.approx(0.3)
    assert result.articles[1].reason == "insufficient_novelty"
    assert result.last_meaningful_update_at == OLD


def test_a_compilation_of_existing_reports_does_not_refresh_with_a_changed_embedding():
    update_time = NOW - timedelta(hours=12)
    result = score(article(1), article(2, content=UPDATE, embedding=(0.0, 1.0), published_at=update_time),
                   article(3, content=REPORT + " " + UPDATE, embedding=(-1.0, -1.0), published_at=NOW))
    compilation = result.articles[2]
    assert compilation.novelty > 0.5  # The text guard prevents semantic noise refreshing the event.
    assert compilation.new_text_fraction < 0.2
    assert compilation.reason == "insufficient_novelty"
    assert result.last_meaningful_update_at == update_time


@pytest.mark.parametrize("content", [None, "Short breaking update.", "subscribe now " * 100])
def test_missing_or_insufficient_bodies_cannot_refresh_from_new_summary_embedding_or_flags(content):
    result = score(article(1), article(2, content=content, summary=UPDATE, embedding=(0.0, 1.0),
                                     published_at=NOW, originality_score=1.0, is_primary_source=True,
                                     is_syndicated=False))
    assert result.last_meaningful_update_at == OLD
    assert result.articles[1].reason == "insufficient_content"


def test_missing_novelty_comparison_does_not_turn_a_fallback_into_a_development():
    old = article(1, content=None, summary=None, embedding=())
    current = article(2, content=UPDATE, summary=None, embedding=(), published_at=NOW)
    result = score(old, current)
    assert result.articles[1].novelty == 0.5
    assert result.articles[1].reason == "insufficient_comparison"
    assert result.last_meaningful_update_at is None
    assert result.decay_started_at == OLD
    assert result.anchor_basis == "first_report_fallback"


def test_semantic_comparison_alone_does_not_establish_new_written_content():
    result = score(article(1, content=None, summary=None),
                   article(2, content=UPDATE, embedding=(0.0, 1.0), published_at=NOW))
    assert result.articles[1].novelty == 1.0
    assert result.articles[1].new_text_fraction is None
    assert result.articles[1].reason == "insufficient_comparison"
    assert result.decay_started_at == OLD


def test_text_only_reports_can_establish_a_development_when_embeddings_are_unavailable():
    result = score(article(1, embedding=()), article(2, content=UPDATE, embedding=(), published_at=NOW))
    assert result.last_meaningful_update_at == NOW
    assert result.freshness_score == 1.0


def test_a_development_from_the_same_publisher_can_refresh_despite_repetition_discounts():
    result = score(article(1), article(2, publisher_key="publisher-1", content=UPDATE,
                                     embedding=(0.0, 1.0), published_at=NOW))
    assert result.last_meaningful_update_at == NOW
    assert result.articles[1].qualifies_as_development


def test_known_syndicated_reporting_without_a_family_cannot_refresh():
    result = score(article(1), article(2, content=UPDATE, embedding=(0.0, 1.0),
                                     published_at=NOW, is_syndicated=True))
    assert result.articles[1].reason == "syndicated_copy"
    assert result.last_meaningful_update_at == OLD


def test_a_flagged_syndicated_family_representative_cannot_refresh_an_existing_event():
    result = score(article(1), article(2, content=UPDATE, embedding=(0.0, 1.0),
                                     published_at=NOW, is_syndicated=True),
                   article(3, content=UPDATE, published_at=NOW))
    assert result.last_meaningful_update_at == OLD
    assert [item.reason for item in result.articles[1:]] == ["syndicated_copy", "syndicated_copy"]


def test_copies_alone_without_an_event_anchor_do_not_create_a_fresh_event():
    result = score(article(1, published_at=NOW, is_syndicated=True))
    assert result.freshness_score == 0
    assert result.age_hours is result.decay_started_at is result.last_meaningful_update_at is None
    assert result.anchor_basis == "unavailable"


def test_known_old_creation_time_protects_an_event_whose_only_observed_report_is_a_recent_copy():
    result = score(article(published_at=NOW, is_syndicated=True), created_at=OLD, changed_at=NOW)
    assert result.freshness_score == 0.25
    assert result.decay_started_at == OLD
    assert result.last_meaningful_update_at is None
    assert result.anchor_basis == "event_creation_fallback"


def test_no_comparison_history_cannot_refresh_an_older_existing_event():
    result = score(article(published_at=NOW), created_at=OLD)
    assert result.freshness_score == 0.25
    assert result.last_meaningful_update_at is None
    assert result.articles[0].reason == "insufficient_comparison"


def test_old_syndicated_observation_prevents_a_later_paraphrase_from_becoming_a_new_fallback_anchor():
    result = score(article(1, is_syndicated=True), article(2, content=PARAPHRASE, published_at=NOW))
    assert result.last_meaningful_update_at is None
    assert result.decay_started_at == OLD
    assert result.freshness_score == 0.25


def test_unknown_reports_use_the_earliest_observation_as_an_explicit_fallback():
    result = score(article(1, content=None), article(2, content=None, published_at=NOW))
    assert result.last_meaningful_update_at is None
    assert result.decay_started_at == OLD
    assert result.anchor_basis == "first_report_fallback"
    assert result.freshness_score == 0.25


def test_late_first_seen_and_later_creation_do_not_replace_an_old_publication_time():
    result = score(article(first_seen_at=NOW), created_at=NOW, changed_at=NOW)
    assert result.last_meaningful_update_at == OLD
    assert result.freshness_score == 0.25


def test_future_publication_and_first_seen_values_are_filtered_before_clock_selection():
    result = score(article(1), article(2, content=UPDATE, embedding=(0.0, 1.0),
                                     published_at=NOW + timedelta(seconds=1)),
                   article(3, content=UPDATE, embedding=(0.0, 1.0), published_at=NOW,
                           first_seen_at=NOW + timedelta(seconds=1)))
    assert result.last_meaningful_update_at == OLD
    assert result.excluded_article_ids == (2, 3)


def test_no_eligible_articles_produce_zero_even_with_cluster_timestamps():
    result = score(article(published_at=NOW + timedelta(days=1)), created_at=OLD, changed_at=NOW)
    assert result.freshness_score == 0
    assert result.decay_started_at is None
    assert result.articles == ()
    assert result.anchor_basis == "unavailable"


def test_future_creation_time_is_not_a_freshness_anchor():
    result = score(article(), created_at=NOW + timedelta(days=1))
    assert result.last_meaningful_update_at == OLD
    assert result.freshness_score == 0.25


@pytest.mark.parametrize(("category", "hours"), [
    ("politika", 24), ("gospodarstvo", 36), ("kriminal", 12), ("sport", 6),
    ("kultura", 72), ("zdravje", 48), ("okolje", 48), ("lokalno", 24),
    ("tehnologija-znanost", 72),
])
def test_every_configured_category_halves_at_its_own_half_life(category, hours):
    result = score(article(published_at=NOW - timedelta(hours=hours)), category=category)
    assert result.category_half_life_hours == hours
    assert not result.used_default_half_life
    assert result.freshness_score == 0.5


def test_category_only_changes_decay_not_initial_freshness_or_other_components():
    config = RankingConfig(version="v1")
    for category in FreshnessConfig().category_half_lives_hours:
        current = RankableCluster(cluster_id=7, articles=(article(published_at=NOW),), category=category)
        neutral = current.model_copy(update={"category": None})
        assert score_freshness(current, NOW, config).freshness_score == 1.0
        assert score_article_contribution(current, NOW, config) == score_article_contribution(neutral, NOW, config)
        assert score_coverage(current, NOW, config) == score_coverage(neutral, NOW, config)
        assert score_publisher_authority(current, NOW, config) == score_publisher_authority(neutral, NOW, config)
    assert score(article(), category="sport").freshness_score < score(article(), category="kultura").freshness_score


@pytest.mark.parametrize("category", [None, "", "not-configured"])
def test_missing_and_unrecognized_categories_use_the_default_half_life(category):
    result = score(article(), category=category, default_half_life_hours=48)
    assert result.used_default_half_life
    assert result.category_half_life_hours == 48
    assert result.freshness_score == 0.5


def test_category_keys_and_custom_half_lives_are_normalized():
    result = score(article(), category=" SPORT ", category_half_lives_hours={" Sport ": 48})
    assert result.category == "sport"
    assert result.category_half_life_hours == 48
    assert result.freshness_score == 0.5
    assert not result.used_default_half_life


def test_partial_category_overrides_preserve_other_categories():
    result = score(article(), category="kultura", category_half_lives_hours={"sport": 8})
    assert result.category_half_life_hours == 72
    assert not result.used_default_half_life


def test_novelty_policy_is_configurable_without_weakening_the_copy_guard():
    paraphrase = article(2, content=PARAPHRASE, published_at=NOW)
    assert score(article(1), paraphrase).last_meaningful_update_at == OLD
    assert score(article(1), paraphrase, minimum_novelty=0.25).last_meaningful_update_at == NOW
    copy = article(2, published_at=NOW)
    assert score(article(1), copy, minimum_novelty=0.01, minimum_new_text_fraction=0.01).last_meaningful_update_at == OLD


def test_publisher_authority_source_flags_and_contribution_weights_do_not_grant_freshness():
    reports = (article(1), article(2, content=PARAPHRASE, published_at=NOW,
                                 publisher_authority_score=1.0, originality_score=1.0,
                                 is_primary_source=True, llm_rank=10))
    result = score(*reports)
    assert result.last_meaningful_update_at == OLD
    config = RankingConfig(version="authority-only", parameters={"article_contribution": {
        "authority_weight": 1, "novelty_weight": 0, "quality_weight": 0,
        "source_weight": 0, "originality_weight": 0, "freshness_half_life_hours": 1,
    }})
    alternate = score_freshness(RankableCluster(cluster_id=7, articles=reports), NOW, config)
    assert alternate.freshness_score == result.freshness_score
    assert alternate.last_meaningful_update_at == result.last_meaningful_update_at


def test_input_order_and_timezone_representation_do_not_change_results():
    reports = (article(1), article(2, content=UPDATE, embedding=(0.0, 1.0), published_at=NOW - timedelta(hours=6)),
               article(3, content=UPDATE, published_at=NOW))
    expected = score(*reports)
    for ordering in permutations(reports):
        assert score(*ordering) == expected
    local = timezone(timedelta(hours=2))
    assert score(article()) == score(article(published_at=OLD.astimezone(local)), evaluated_at=NOW.astimezone(local))


def test_decay_uses_elapsed_time_across_a_daylight_saving_fold():
    zone = ZoneInfo("Europe/Ljubljana")
    before = datetime(2026, 10, 25, 2, 30, tzinfo=zone, fold=0)
    after = before.replace(fold=1)
    result = score(article(published_at=before), evaluated_at=after, default_half_life_hours=1)
    assert result.age_hours == 1
    assert result.freshness_score == 0.5


def test_config_inputs_are_unchanged_and_result_models_are_immutable():
    snapshot = RankableCluster(cluster_id=7, articles=(article(),), category="custom")
    config = RankingConfig(version="custom-v1", parameters={"freshness": {"category_half_lives_hours": {" Custom ": 48}}})
    before = snapshot.model_dump(), config.model_dump()
    result = score_freshness(snapshot, NOW, config)
    assert (snapshot.model_dump(), config.model_dump()) == before
    assert result.freshness_score == 0.5
    with pytest.raises(ValidationError, match="frozen"):
        result.freshness_score = 1.0


@pytest.mark.parametrize("hours", [1e-308, 1e308])
def test_extreme_valid_half_lives_produce_finite_bounded_scores(hours):
    result = score(article(), default_half_life_hours=hours)
    assert isfinite(result.freshness_score)
    assert 0 <= result.freshness_score <= 1


@pytest.mark.parametrize("parameters", [
    {"default_half_life_hours": 0}, {"default_half_life_hours": -1},
    {"default_half_life_hours": float("inf")}, {"default_half_life_hours": float("nan")},
    {"category_half_lives_hours": {"sport": 0}}, {"category_half_lives_hours": {"sport": -1}},
    {"category_half_lives_hours": {"sport": float("inf")}},
    {"category_half_lives_hours": {"sport": float("nan")}},
    {"category_half_lives_hours": {"sport": 6, "SPORT": 12}},
    {"category_half_lives_hours": {" ": 12}},
    {"minimum_novelty": 0}, {"minimum_novelty": 1.1},
    {"minimum_new_text_fraction": 0}, {"minimum_new_text_fraction": 1.1}, {"typo": 24},
])
def test_invalid_freshness_policy_is_rejected(parameters):
    with pytest.raises(ValidationError):
        score(article(), **parameters)


def test_naive_evaluation_time_is_rejected():
    with pytest.raises(ValueError, match="timezone"):
        score(article(), evaluated_at=NOW.replace(tzinfo=None))

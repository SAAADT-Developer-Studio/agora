from datetime import datetime, timedelta, timezone
from itertools import permutations
from math import isfinite

import pytest
from pydantic import ValidationError

from app.ranking import RankableArticle, RankableCluster, RankingConfig, score_article_contribution
from app.tests.ranking.samples import PARAPHRASE, REPORT, UPDATE


NOW = datetime(2026, 9, 13, 12, tzinfo=timezone.utc)


def article(article_id=1, **overrides):
    values = dict(article_id=article_id, publisher_key="publisher", title="Event report",
                  published_at=NOW, first_seen_at=NOW, content=REPORT, summary=REPORT,
                  embedding=(1.0, 0.0), publisher_authority_score=0.7,
                  is_syndicated=False, is_primary_source=False)
    values.update(overrides)
    return RankableArticle(**values)


def score(*articles, evaluated_at=NOW, **parameters):
    return score_article_contribution(
        RankableCluster(cluster_id=7, articles=articles), evaluated_at,
        RankingConfig(version="contribution-test-v1", parameters={"article_contribution": parameters}),
    )


def authority_only():
    return dict(authority_weight=1.0, originality_weight=0.0, novelty_weight=0.0,
                quality_weight=0.0, source_weight=0.0)


def test_result_exposes_components_and_configuration_without_mutating_inputs():
    cluster = RankableCluster(cluster_id=7, articles=(article(),))
    config = RankingConfig(version="custom-v2", parameters={"article_contribution": {"normalization_scale": 2.0}})
    before = cluster.model_dump(), config.model_dump()
    result = score_article_contribution(cluster, NOW, config)
    item = result.articles[0]
    assert item.contribution == pytest.approx(item.base_contribution * item.freshness
                                             * item.syndication_multiplier * item.publisher_multiplier)
    assert result.total_contribution == item.contribution
    assert 0.0 < result.article_contribution_score < 1.0
    assert result.config_version == "custom-v2"
    assert result.algorithm_version == "article-contribution-v2"
    assert result.syndication_algorithm_version == "syndication-v1"
    assert result.model_dump(mode="json")["evaluated_at"] == "2026-09-13T12:00:00Z"
    assert (cluster.model_dump(), config.model_dump()) == before


@pytest.mark.parametrize("signal", ["publisher_authority_score", "originality_score"])
def test_higher_authority_and_originality_increase_contribution(signal):
    low = score(article(**{signal: 0.1})).articles[0]
    high = score(article(**{signal: 0.9})).articles[0]
    assert high.contribution > low.contribution


def test_zero_authority_is_not_replaced_by_missing_value_fallback():
    result = score(article(publisher_authority_score=0.0), **authority_only())
    assert result.articles[0].publisher_authority == 0.0
    assert result.total_contribution == 0.0


def test_syndicated_article_is_discounted_even_with_claimed_high_originality():
    original = score(article(originality_score=1.0, is_syndicated=False)).articles[0]
    syndicated = score(article(originality_score=1.0, is_syndicated=True)).articles[0]
    assert syndicated.syndication_multiplier == 0.35
    assert syndicated.originality == 0.15
    assert syndicated.contribution < original.contribution


def test_freshness_halves_after_configured_half_life():
    now = score(article()).articles[0]
    old = score(article(), evaluated_at=NOW + timedelta(hours=6), freshness_half_life_hours=6).articles[0]
    assert now.freshness == 1.0
    assert old.freshness == pytest.approx(0.5)
    assert old.contribution == pytest.approx(now.contribution / 2)


def test_primary_source_and_earliest_reporting_receive_credit():
    first = article(1, published_at=NOW - timedelta(hours=1))
    later = article(2, publisher_key="other", content=UPDATE, embedding=(0.0, 1.0))
    primary = article(3, publisher_key="primary", is_primary_source=True)
    result = score(first, later, primary)
    assert [item.source_credit for item in result.articles] == [0.75, 0.0, 1.0]
    assert score(article(is_primary_source=True)).total_contribution > score(article()).total_contribution


def test_same_time_reports_share_breaking_credit():
    result = score(article(1), article(2, publisher_key="other"))
    assert [item.source_credit for item in result.articles] == [0.75, 0.75]


def test_quality_rewards_available_content_summary_and_usable_embedding():
    bare = score(article(content=None, summary=None, embedding=())).articles[0]
    full = score(article(content=REPORT * 10, summary=REPORT * 2)).articles[0]
    assert bare.data_quality == 0.2
    assert full.data_quality == 1.0
    assert full.contribution > bare.contribution


def test_exact_republication_loses_originality_novelty_and_syndication_credit():
    result = score(article(1, published_at=NOW - timedelta(minutes=10)),
                   article(2, publisher_key="other", content=REPORT.upper(), embedding=(0.0, 1.0)))
    repeated = result.articles[1]
    assert repeated.max_text_reuse == 1.0
    assert repeated.originality == 0.0
    assert repeated.novelty == 0.0  # a changed embedding cannot make copied text novel
    assert repeated.syndication_multiplier == 0.35
    assert repeated.contribution < result.articles[0].contribution


def test_semantically_repeated_paraphrase_gets_less_novelty_than_new_information():
    earlier = article(1, published_at=NOW - timedelta(hours=1))
    paraphrase = score(earlier, article(2, publisher_key="other", content=PARAPHRASE)).articles[1]
    update = score(earlier, article(2, publisher_key="other", content=UPDATE, embedding=(0.0, 1.0))).articles[1]
    assert paraphrase.max_semantic_similarity == pytest.approx(1.0)
    assert paraphrase.novelty < update.novelty
    assert update.originality == 1.0
    assert update.contribution > paraphrase.contribution


def test_novelty_compares_with_union_of_existing_reports():
    result = score(article(1, content=REPORT, embedding=(), published_at=NOW - timedelta(hours=2)),
                   article(2, content=UPDATE, embedding=(), published_at=NOW - timedelta(hours=1)),
                   article(3, content=REPORT + " " + UPDATE, embedding=()))
    assert result.articles[2].novelty < 0.15
    assert result.articles[2].compared_article_count == 2


def test_repeated_publisher_contributions_decay_and_other_publishers_start_fresh():
    result = score(*(article(i, content=None, summary=None, embedding=(), publisher_authority_score=0.8,
                             publisher_key="PUBLISHER" if i == 2 else "publisher") for i in range(1, 4)),
                   article(4, content=None, summary=None, embedding=(), publisher_key="other", publisher_authority_score=0.8),
                   **authority_only())
    assert [item.publisher_multiplier for item in result.articles] == [1.0, 0.5, 0.25, 1.0]
    assert [item.contribution for item in result.articles] == pytest.approx([0.8, 0.4, 0.2, 0.8])


def test_publisher_repeat_total_is_bounded_even_for_many_reports():
    result = score(*(article(i, content=None, summary=None, embedding=(), publisher_authority_score=1.0)
                     for i in range(1, 40)), **authority_only())
    assert result.total_contribution < 2.0
    assert result.articles[-1].contribution < result.articles[0].contribution


def test_scores_are_independent_of_input_order_and_repeatable():
    articles = (article(3), article(1), article(2, publisher_key="other", content=UPDATE))
    baseline = score(*articles)
    for ordering in permutations(articles):
        assert score(*ordering) == baseline
    assert [item.article_id for item in baseline.articles] == [1, 2, 3]


def test_future_articles_are_excluded_from_credit_comparisons_and_publisher_counts():
    published_later = article(1, published_at=NOW + timedelta(seconds=1))
    seen_later = article(2, published_at=NOW - timedelta(days=1), first_seen_at=NOW + timedelta(seconds=1))
    valid = article(3)
    result = score(published_later, seen_later, valid)
    assert result.excluded_article_ids == (1, 2)
    assert result.articles[0].publisher_ordinal == 1
    assert result.articles[0].compared_article_count == 0
    assert result.total_contribution == score(valid).total_contribution


def test_no_eligible_articles_produce_zero_contribution():
    result = score(article(published_at=NOW + timedelta(days=1)))
    assert result.articles == ()
    assert result.total_contribution == result.article_contribution_score == 0.0


def test_naive_evaluation_time_is_rejected():
    with pytest.raises(ValueError, match="timezone"):
        score(article(), evaluated_at=NOW.replace(tzinfo=None))


def test_equivalent_timezones_produce_identical_results():
    local = timezone(timedelta(hours=2))
    assert score(article()) == score(article(published_at=NOW.astimezone(local), first_seen_at=NOW.astimezone(local)), evaluated_at=NOW.astimezone(local))


def test_missing_signals_have_explicit_non_extreme_fallbacks():
    result = score(RankableArticle(article_id=1, publisher_key="publisher", title="Title", published_at=NOW)).articles[0]
    assert result.publisher_authority == result.originality == result.novelty == 0.5
    assert result.syndication_multiplier == 0.85
    assert set(result.fallback_signals) == {"publisher_authority", "originality", "novelty", "syndication", "primary_source"}


@pytest.mark.parametrize("vector", [(), (0.0, 0.0), (1.0, 0.0, 0.0)])
def test_missing_zero_and_incompatible_embeddings_use_available_text(vector):
    result = score(article(1, published_at=NOW - timedelta(hours=1)), article(2, content=UPDATE, embedding=vector))
    assert result.articles[1].max_semantic_similarity is None
    assert result.articles[1].novelty == 1.0


def test_very_large_finite_embeddings_do_not_overflow():
    result = score(article(1, embedding=(1e308, 1e308)), article(2, content=UPDATE, embedding=(1e308, 1e308)))
    assert result.articles[1].max_semantic_similarity == pytest.approx(1.0)
    assert isfinite(result.total_contribution)


@pytest.mark.parametrize("parameters", [
    {"freshness_half_life_hours": 0}, {"publisher_repeat_decay": 1},
    {"publisher_repeat_decay": -0.1}, {"authority_weight": float("inf")},
    {"minimum_text_tokens": 4}, {"novelty_similarity_floor": 0.99},
    {"syndication_multiplier": 0.9}, {"typo_weight": 0.2},
    {key: 0 for key in authority_only()},
])
def test_invalid_policy_is_rejected(parameters):
    with pytest.raises(ValidationError):
        score(article(), **parameters)


def test_other_ranking_configuration_is_ignored_without_mutation():
    cluster = RankableCluster(cluster_id=7, articles=(article(),))
    config = RankingConfig(version="v1", parameters={"other_component": {"weight": 0.9}})
    assert score_article_contribution(cluster, NOW, config).config_version == "v1"
    assert config.parameters == {"other_component": {"weight": 0.9}}


@pytest.mark.parametrize("value", [-0.1, 1.1, float("nan")])
def test_originality_input_must_be_a_finite_unit_score(value):
    with pytest.raises(ValidationError):
        article(originality_score=value)


def test_four_copies_count_as_one_report_plus_small_distribution_credit():
    copies = score(*(article(i, publisher_key=f"publisher-{i}") for i in range(1, 5)),
                   **authority_only())
    representative = copies.articles[0].contribution
    assert [family.article_ids for family in copies.syndicated_families] == [(1, 2, 3, 4)]
    assert copies.total_contribution == pytest.approx(representative * 1.13125)
    assert representative < copies.total_contribution < representative * 1.15
    for item in copies.articles:
        assert item.syndication_status == "syndicated_duplicated"
        assert item.family_representative_article_id == 1
        assert item.contribution == pytest.approx(
            item.base_contribution * item.syndication_multiplier * item.freshness
            * item.publisher_multiplier * item.family_multiplier
        )
    independent = score(*(
        article(i, publisher_key=f"publisher-{i}", content=body)
        for i, body in enumerate((REPORT, UPDATE, PARAPHRASE,
                                 " ".join(f"detail{n}" for n in range(70))), 1)
    ), **authority_only())
    assert independent.syndicated_families == ()
    assert independent.total_contribution == pytest.approx(representative * 4)


@pytest.mark.parametrize(("budget", "decay"), [(0.0, 0.5), (0.15, 0.5), (0.25, 0.8)])
def test_family_credit_is_bounded_across_many_publishers(budget, decay):
    result = score(*(article(i, publisher_key=f"publisher-{i}") for i in range(1, 101)),
                   family_distribution_credit=budget, family_distribution_decay=decay,
                   **authority_only())
    main = result.articles[0].contribution
    assert result.total_contribution <= main * (1 + budget) + 1e-12
    assert result.total_contribution == pytest.approx(
        main * (1 + budget * (1 - decay ** 99))
    )


def test_same_publisher_copies_add_no_distribution_credit_or_consume_new_publisher_allowance():
    result = score(article(1, publisher_key="source"), article(2, publisher_key="SOURCE"),
                   article(3, publisher_key="other"), article(4, publisher_key="OTHER"),
                   article(5, publisher_key="third"), **authority_only())
    main = result.articles[0].contribution
    assert [item.contribution for item in result.articles] == pytest.approx(
        [main, 0.0, main * 0.075, 0.0, main * 0.0375]
    )


def test_each_distinct_family_has_its_own_distribution_allowance():
    result = score(article(1, publisher_key="one"), article(2, publisher_key="two"),
                   article(3, publisher_key="three", content=UPDATE),
                   article(4, publisher_key="four", content=UPDATE), **authority_only())
    first, copy, second, other_copy = result.articles
    assert len(result.syndicated_families) == 2
    assert copy.contribution == pytest.approx(first.contribution * 0.075)
    assert other_copy.contribution == pytest.approx(second.contribution * 0.075)


def test_claimed_originality_and_primary_source_flags_cannot_bypass_family_cap():
    result = score(article(1, publisher_key="source"),
                   article(2, publisher_key="copy", is_syndicated=False,
                           originality_score=1.0, is_primary_source=True))
    copy = result.articles[1]
    assert copy.syndication_status == "syndicated_duplicated"
    assert copy.originality == 0.15
    assert copy.contribution <= result.articles[0].contribution * 0.075


def test_family_counts_writing_once_even_when_all_observed_members_are_flagged_syndicated():
    result = score(article(1, publisher_key="one", is_syndicated=True),
                   article(2, publisher_key="two", is_syndicated=True), **authority_only())
    main, copy = result.articles
    assert main.syndication_multiplier == 1.0
    assert copy.syndication_multiplier == 0.35
    assert result.total_contribution == pytest.approx(main.contribution * 1.075)


def test_unknown_body_does_not_inherit_a_family_from_summary_or_embeddings():
    result = score(article(1), article(2, content=None, is_syndicated=None))
    unknown = result.articles[1]
    assert unknown.syndication_status == "unknown"
    assert unknown.syndication_family_id is None
    assert unknown.originality == 0.5
    assert unknown.syndication_multiplier == 0.85
    assert unknown.family_multiplier == 1.0
    assert result.syndicated_families == ()


def test_sufficient_independent_body_does_not_need_an_upstream_originality_flag():
    independent = score(article(is_syndicated=None)).articles[0]
    assert independent.syndication_status == "independently_written"
    assert independent.originality == independent.syndication_multiplier == 1.0
    assert "originality" not in independent.fallback_signals
    assert "syndication" not in independent.fallback_signals


def test_zero_family_representative_credit_cannot_be_revived_by_copies():
    result = score(article(1, publisher_key="source", publisher_authority_score=0.0),
                   article(2, publisher_key="copy", publisher_authority_score=1.0),
                   **authority_only())
    assert result.total_contribution == 0.0
    assert result.articles[1].family_multiplier == 0.0


def test_distribution_allowance_never_increases_a_copy_above_its_other_factors():
    result = score(article(1, publisher_key="source", publisher_authority_score=1.0),
                   article(2, publisher_key="copy", publisher_authority_score=0.001),
                   **authority_only())
    copy = result.articles[1]
    assert copy.family_multiplier == 1.0
    assert copy.contribution == pytest.approx(0.001 * 0.35)


def test_new_copies_do_not_refresh_the_main_report_in_a_family():
    original = article(1, publisher_key="source", published_at=NOW - timedelta(days=2))
    alone = score(original, **authority_only())
    copies = score(original, article(2, publisher_key="copy"), **authority_only())
    assert copies.articles[0].contribution == alone.total_contribution
    assert copies.total_contribution == pytest.approx(alone.total_contribution * 1.075)


def test_contribution_uses_configured_detection_threshold():
    cluster = RankableCluster(cluster_id=7, articles=(article(1), article(2, content=REPORT.replace("spring", "summer"))))
    config = RankingConfig(version="strict-v1", parameters={"syndication": {"similarity_threshold": 1.0}})
    assert score_article_contribution(cluster, NOW, config).syndicated_families == ()
    assert len(score_article_contribution(cluster, NOW, RankingConfig(version="v1")).syndicated_families) == 1


@pytest.mark.parametrize("parameters", [
    {"family_distribution_credit": -0.1}, {"family_distribution_credit": 1.0},
    {"family_distribution_decay": 0.0}, {"family_distribution_decay": 1.0},
])
def test_invalid_family_policy_is_rejected(parameters):
    with pytest.raises(ValidationError):
        score(article(), **parameters)

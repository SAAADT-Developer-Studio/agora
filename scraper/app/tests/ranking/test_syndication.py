from datetime import datetime, timedelta, timezone
from itertools import permutations
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from app.ranking import RankableArticle, RankableCluster, RankingConfig, detect_syndication
from app.tests.ranking.samples import PARAPHRASE, REPORT, UPDATE


NOW = datetime(2026, 9, 13, 12, tzinfo=timezone.utc)


def article(article_id=1, **overrides):
    values = dict(article_id=article_id, publisher_key=f"publisher-{article_id}",
                  title="Council approves railway station", content=REPORT,
                  summary=REPORT, embedding=(1.0, 0.0), published_at=NOW)
    values.update(overrides)
    return RankableArticle(**values)


def detect(*articles, evaluated_at=NOW, **parameters):
    return detect_syndication(
        RankableCluster(cluster_id=7, articles=articles), evaluated_at,
        RankingConfig(version="test-v1", parameters={"syndication": parameters}),
    )


def test_three_outcomes_and_explainable_family_membership():
    result = detect(article(1), article(2), article(3, content=UPDATE), article(4, content=None))
    assert [item.status for item in result.articles] == [
        "syndicated_duplicated", "syndicated_duplicated", "independently_written", "unknown",
    ]
    family, = result.families
    assert family.article_ids == (1, 2)
    assert family.representative_article_id == 1
    assert family.minimum_text_similarity == 1.0
    assert [item.family_id for item in result.articles] == [family.family_id, family.family_id, None, None]
    assert [item.originality_score for item in result.articles] == [1.0, 0.0, 1.0, None]
    assert result.config_version == "test-v1"
    assert result.algorithm_version == "syndication-v1"
    assert result.model_dump(mode="json")["articles"][3]["status"] == "unknown"


@pytest.mark.parametrize("copy", [
    REPORT.upper().replace(" ", " \n\t "),
    REPORT.replace(".", "!"),
    REPORT.replace("railway", "ＲＡＩＬＷＡＹ"),
    REPORT.replace("spring", "summer"),
    "An agency report follows. " + REPORT + " More details will follow.",
    " ".join(reversed(REPORT.split(". "))),
])
def test_formatting_minor_edits_and_reordered_paragraphs_share_a_family(copy):
    result = detect(article(1), article(2, content=copy))
    assert len(result.families) == 1
    assert result.families[0].article_ids == (1, 2)
    assert result.articles[1].max_text_similarity >= 0.8


def test_same_facts_title_summary_and_embedding_do_not_prove_copied_writing():
    result = detect(article(1), article(2, content=PARAPHRASE))
    assert result.families == ()
    assert all(item.status == "independently_written" for item in result.articles)


def test_common_quote_and_boilerplate_do_not_merge_otherwise_distinct_reports():
    shared = "Officials said public safety remains our highest priority throughout the project."
    result = detect(article(1, content=REPORT + shared), article(2, content=UPDATE + shared))
    assert result.families == ()


def test_shared_excerpt_does_not_collapse_a_substantially_longer_report():
    result = detect(article(1), article(2, content=REPORT + " " + UPDATE))
    assert result.families == ()


@pytest.mark.parametrize(("body", "reason"), [
    (None, "content_unavailable"), ("", "content_unavailable"),
    ("  !!!  ", "content_unavailable"),
    ("A short update without enough written content.", "insufficient_content"),
    (" ".join(REPORT.split()[:49]), "insufficient_content"),
    ("subscribe to our newsletter " * 30, "insufficient_distinct_content"),
])
def test_insufficient_body_is_unknown_even_with_matching_summary_and_embedding(body, reason):
    result = detect(article(1), article(2, content=body, is_syndicated=False, originality_score=1.0))
    outcome = result.articles[1]
    assert outcome.status == "unknown"
    assert outcome.reason == reason
    assert outcome.family_id is outcome.originality_score is outcome.max_text_similarity is None
    assert result.families == ()


def test_identical_short_bodies_remain_unknown_and_are_not_one_family():
    result = detect(article(1, content="Short report"), article(2, content="Short report"))
    assert all(item.status == "unknown" for item in result.articles)
    assert result.families == ()


def test_minimum_body_length_is_inclusive_and_threshold_is_configurable():
    boundary = " ".join(REPORT.split()[:50])
    assert len(detect(article(1, content=boundary), article(2, content=boundary)).families) == 1
    edited = article(2, content=REPORT.replace("spring", "summer"))
    assert len(detect(article(1), edited).families) == 1
    assert detect(article(1), edited, similarity_threshold=1.0).families == ()


def test_distinct_families_and_singletons_are_kept_separate():
    result = detect(article(1), article(2), article(3, content=UPDATE),
                    article(4, content=UPDATE), article(5, content=PARAPHRASE))
    assert [family.article_ids for family in result.families] == [(1, 2), (3, 4)]
    assert result.articles[4].status == "independently_written"


def test_pairwise_matching_prevents_a_bridge_from_merging_different_reports():
    # A and C replace different 30-word spans of B: each matches B, but not each other.
    middle = [f"word{index}" for index in range(200)]
    left, right = middle.copy(), middle.copy()
    left[20:50] = [f"left{index}" for index in range(30)]
    right[120:150] = [f"right{index}" for index in range(30)]
    a, b, c = (article(index, content=" ".join(words))
               for index, words in enumerate((left, middle, right), 1))
    assert len(detect(a, b).families) == len(detect(b, c).families) == 1
    assert detect(a, c).families == ()
    result = detect(a, b, c)
    assert [family.article_ids for family in result.families] == [(1, 2)]


def test_publication_first_seen_then_id_choose_representative_independent_of_input_order():
    reports = (article(3, first_seen_at=NOW), article(2, first_seen_at=NOW - timedelta(minutes=1)),
               article(1, first_seen_at=NOW - timedelta(minutes=1)))
    baseline = detect(*reports)
    assert baseline.families[0].article_ids == (1, 2, 3)
    for ordering in permutations(reports):
        assert detect(*ordering) == baseline
    older = article(4, published_at=NOW - timedelta(hours=1))
    assert detect(*reports, older).families[0].representative_article_id == 4


def test_timezones_and_daylight_saving_fold_order_by_actual_instant():
    zone = ZoneInfo("Europe/Ljubljana")
    first = datetime(2026, 10, 25, 2, 30, tzinfo=zone, fold=0)
    second = first.replace(fold=1)
    result = detect(article(1, published_at=second), article(2, published_at=first),
                    evaluated_at=second + timedelta(hours=3))
    assert result.families[0].representative_article_id == 2
    assert result == detect(
        article(1, published_at=second.astimezone(timezone.utc)),
        article(2, published_at=first.astimezone(timezone.utc)),
        evaluated_at=(second + timedelta(hours=3)).astimezone(timezone.utc),
    )


def test_future_publications_and_late_observations_cannot_form_families():
    result = detect(article(1), article(2, published_at=NOW + timedelta(seconds=1)),
                    article(3, published_at=NOW - timedelta(days=1),
                            first_seen_at=NOW + timedelta(seconds=1)))
    assert result.excluded_article_ids == (2, 3)
    assert result.families == ()
    assert result.articles[0].status == "independently_written"
    empty = detect(article(1, published_at=NOW + timedelta(days=1)))
    assert empty.articles == empty.families == ()


def test_inputs_are_unchanged_and_unknown_flags_do_not_invent_a_family():
    cluster = RankableCluster(cluster_id=7, articles=(article(is_syndicated=True, content=None),))
    config = RankingConfig(version="test-v1", parameters={"other": {"weight": 0.5}})
    before = cluster.model_dump(), config.model_dump()
    result = detect_syndication(cluster, NOW, config)
    assert result.articles[0].status == "unknown"
    assert result.families == ()
    assert (cluster.model_dump(), config.model_dump()) == before


@pytest.mark.parametrize("parameters", [
    {"minimum_content_tokens": 4}, {"minimum_unique_shingles": 0},
    {"similarity_threshold": 0}, {"similarity_threshold": 1.1},
    {"similarity_threshold": float("nan")}, {"similarity_threshold": float("inf")},
    {"typo": 0.8},
])
def test_invalid_detection_policy_is_rejected(parameters):
    with pytest.raises(ValidationError):
        detect(article(), **parameters)


def test_naive_evaluation_time_is_rejected():
    with pytest.raises(ValueError, match="timezone"):
        detect(article(), evaluated_at=NOW.replace(tzinfo=None))

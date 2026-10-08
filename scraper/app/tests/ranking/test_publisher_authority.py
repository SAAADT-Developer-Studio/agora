from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone
from itertools import permutations
from types import SimpleNamespace
import subprocess
import sys

import pytest
from pydantic import ValidationError

from app.providers.enums import ProviderKey
from app.providers.ranks import RANKS, assign_ranks, get_rank_map
from app.ranking import (
    ManualAuthorityProvider, PublisherAuthorityProvider, RankableArticle, RankableCluster,
    RankingConfig, normalize_manual_authority, score_article_contribution,
    score_publisher_authority, with_publisher_authority,
)
from app.tests.ranking.samples import PARAPHRASE, REPORT, UPDATE


NOW = datetime(2026, 9, 13, 12, tzinfo=timezone.utc)


def article(article_id=1, **overrides):
    values = dict(article_id=article_id, publisher_key=f"publisher-{article_id}",
                  title="Event report", content=REPORT, published_at=NOW)
    values.update(overrides)
    return RankableArticle(**values)


def cluster(*articles):
    return RankableCluster(cluster_id=7, articles=articles)


def score(*articles, evaluated_at=NOW, **parameters):
    return score_publisher_authority(
        cluster(*articles), evaluated_at,
        RankingConfig(version="authority-test-v1", parameters={"publisher_authority": parameters}),
    )


@pytest.mark.parametrize(("rank", "expected"), [(0, 1.0), (1, 0.75), (2, 0.5), (3, 0.25), (4, 0.0)])
def test_manual_tiers_normalize_in_the_correct_direction(rank, expected):
    assert normalize_manual_authority(rank) == expected


@pytest.mark.parametrize("rank", [-1, 5, 100, 1.5, 0.0, "0", True, False, float("nan"), float("inf")])
def test_invalid_manual_ranks_are_rejected_instead_of_clamped(rank):
    with pytest.raises(ValueError, match="integer from 0 to 4"):
        normalize_manual_authority(rank)


def test_unknown_manual_authority_is_distinct_from_the_lowest_known_authority():
    provider = ManualAuthorityProvider({"lowest": 4, "unset": None})
    assert normalize_manual_authority(None) is None
    assert provider.get_authority("lowest") == 0.0
    assert provider.get_authority("unset") is None
    assert provider.get_authority("unlisted") is None


def test_default_provider_uses_the_complete_existing_manual_table():
    provider = ManualAuthorityProvider()
    mapping = get_rank_map()
    assert set(mapping) == {key.value for key in ProviderKey}
    for rank, keys in RANKS.items():
        for key in keys:
            assert provider.get_authority(key.value) == normalize_manual_authority(rank)
    assert provider.get_authority("24ur") == 1.0
    assert provider.get_authority("delo") == 0.75
    assert provider.get_authority("sta") == 0.5
    assert provider.get_authority("finance") == 0.25
    assert provider.get_authority("slotech") == 0.0


def test_normalization_does_not_depend_on_which_publishers_are_loaded():
    alone = ManualAuthorityProvider({"middle": 2})
    together = ManualAuthorityProvider({"best": 0, "middle": 2, "worst": 4})
    assert alone.get_authority("middle") == together.get_authority("middle") == 0.5


def test_manual_provider_canonicalizes_keys_and_freezes_a_copy_of_its_input():
    ranks = {" RTV ": 0}
    provider = ManualAuthorityProvider(ranks)
    ranks[" RTV "] = 4
    assert provider.get_authority("  rTv  ") == 1.0
    with pytest.raises(TypeError):
        provider.ranks["rtv"] = 4
    with pytest.raises(FrozenInstanceError):
        provider.ranks = {}


@pytest.mark.parametrize("mapping", [{"RTV": 0, "rtv": 1}, {" ": 0}, {3: 0}, {"rtv": 5}])
def test_invalid_manual_snapshots_are_rejected(mapping):
    with pytest.raises(ValueError):
        ManualAuthorityProvider(mapping)


def test_rank_map_is_shared_with_existing_provider_assignment():
    providers = [SimpleNamespace(key=key.value, rank=None) for key in ProviderKey]
    assign_ranks(providers)
    assert {provider.key: provider.rank for provider in providers} == get_rank_map()


def test_duplicate_manual_entries_are_rejected_before_provider_assignment(monkeypatch):
    from app.providers import ranks

    monkeypatch.setattr(ranks, "RANKS", {0: [ProviderKey.RTV], 1: [ProviderKey.RTV]})
    provider = SimpleNamespace(key="rtv", rank=3)
    with pytest.raises(ValueError, match="Duplicate provider key"):
        assign_ranks([provider])
    assert provider.rank == 3


def test_authority_imports_do_not_initialize_scraping_configuration_or_provider_instances():
    result = subprocess.run(
        [sys.executable, "-c", "from app.ranking import ManualAuthorityProvider; import sys; "
         "assert ManualAuthorityProvider().get_authority('rtv') == 1.0; "
         "assert 'app.config' not in sys.modules; "
         "assert 'app.providers.providers' not in sys.modules; "
         "assert 'database.schema' not in sys.modules"],
        check=False, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr


def test_preparation_looks_up_each_canonical_publisher_once_and_preserves_the_input():
    class CountingProvider:
        def __init__(self):
            self.calls = []

        def get_authority(self, publisher_key):
            self.calls.append(publisher_key)
            return {"rtv": 1.0, "delo": 0.75}[publisher_key]

    provider = CountingProvider()
    original = cluster(article(1, publisher_key="RTV", publisher_authority_score=0.2),
                       article(2, publisher_key=" rtv "), article(3, publisher_key="delo"))
    before = original.model_dump()
    prepared = with_publisher_authority(original, provider)
    assert provider.calls == ["delo", "rtv"]
    assert [item.publisher_authority_score for item in prepared.articles] == [1.0, 1.0, 0.75]
    assert original.model_dump() == before
    assert [item.article_id for item in prepared.articles] == [1, 2, 3]
    assert prepared.cluster_id == original.cluster_id
    assert all(old.model_dump(exclude={"publisher_authority_score"}) ==
               new.model_dump(exclude={"publisher_authority_score"})
               for old, new in zip(original.articles, prepared.articles, strict=True))


def test_preparation_replaces_old_values_with_unknown_when_the_supplied_snapshot_has_no_value():
    prepared = with_publisher_authority(
        cluster(article(publisher_authority_score=0.9)), ManualAuthorityProvider({}),
    )
    assert prepared.articles[0].publisher_authority_score is None


@pytest.mark.parametrize("value", [-0.1, 1.1, float("nan"), float("inf"), "0.5", True])
def test_invalid_values_from_any_authority_provider_are_rejected_at_the_boundary(value):
    class BadProvider:
        def get_authority(self, publisher_key):
            return value

    with pytest.raises(ValidationError):
        with_publisher_authority(cluster(article()), BadProvider())


def test_provider_failures_are_not_silently_replaced_with_unknown_authority():
    class FailedProvider:
        def get_authority(self, publisher_key):
            raise RuntimeError("authority snapshot unavailable")

    with pytest.raises(RuntimeError, match="authority snapshot unavailable"):
        with_publisher_authority(cluster(article()), FailedProvider())


def test_swapping_the_authority_implementation_requires_no_ranking_function_changes():
    class CalculatedAuthorityProvider:
        def get_authority(self, publisher_key: str) -> float | None:
            # Stand-in for a precomputed dynamic authority snapshot.
            return {"rtv": 1.0, "delo": 0.75}.get(publisher_key)

    manual: PublisherAuthorityProvider = ManualAuthorityProvider()
    calculated: PublisherAuthorityProvider = CalculatedAuthorityProvider()
    original = cluster(article(1, publisher_key="rtv"), article(2, publisher_key="delo", content=UPDATE))
    config = RankingConfig(version="same-ranking-function-v1")
    manual_snapshot = with_publisher_authority(original, manual)
    calculated_snapshot = with_publisher_authority(original, calculated)
    assert manual_snapshot == calculated_snapshot
    assert score_publisher_authority(manual_snapshot, NOW, config) == score_publisher_authority(calculated_snapshot, NOW, config)
    assert score_article_contribution(manual_snapshot, NOW, config) == score_article_contribution(calculated_snapshot, NOW, config)


def test_manual_authority_reaches_the_existing_article_contribution_factor():
    prepared = with_publisher_authority(
        cluster(article(1, publisher_key="rtv"), article(2, publisher_key="slotech", content=UPDATE)),
        ManualAuthorityProvider(),
    )
    result = score_article_contribution(prepared, NOW, RankingConfig(version="v1"))
    assert [item.publisher_authority for item in result.articles] == [1.0, 0.0]
    assert all("publisher_authority" not in item.fallback_signals for item in result.articles)


def test_component_averages_distinct_independent_publishers_with_explainable_output():
    result = score(article(1, publisher_authority_score=1.0),
                   article(2, content=UPDATE, publisher_authority_score=0.5))
    assert result.publisher_authority_score == 0.75
    assert result.effective_publisher_count == 2.0
    assert [item.coverage_weight for item in result.publishers] == [1.0, 1.0]
    assert all(not item.used_fallback for item in result.publishers)
    assert result.algorithm_version == "publisher-authority-v1"
    assert result.coverage_algorithm_version == "coverage-v1"
    assert result.syndication_algorithm_version == "syndication-v1"
    assert result.config_version == "authority-test-v1"
    assert result.model_dump(mode="json")["evaluated_at"] == "2026-09-13T12:00:00Z"


def test_increasing_a_publisher_authority_increases_the_component():
    other = article(1, publisher_authority_score=0.4)
    low = score(other, article(2, content=UPDATE, publisher_authority_score=0.2))
    high = score(other, article(2, content=UPDATE, publisher_authority_score=0.9))
    assert high.publisher_authority_score > low.publisher_authority_score


def test_unknown_authority_uses_a_visible_configurable_fallback_but_zero_is_known():
    unknown = score(article()).publishers[0]
    zero = score(article(publisher_authority_score=0.0)).publishers[0]
    assert unknown.authority_score == 0.5 and unknown.used_fallback
    assert zero.authority_score == 0.0 and not zero.used_fallback
    assert score(article(), unknown_authority=0.3).publisher_authority_score == 0.3


def test_repeated_articles_do_not_multiply_one_publishers_authority():
    first = article(1, publisher_authority_score=1.0)
    other = article(2, content=UPDATE, publisher_authority_score=0.0)
    copies = tuple(article(index, publisher_key="publisher-1", publisher_authority_score=1.0)
                   for index in range(3, 23))
    assert score(first, other).publisher_authority_score == score(first, other, *copies).publisher_authority_score == 0.5


def test_syndicated_publishers_receive_small_weights_in_the_authority_average():
    result = score(article(1, publisher_authority_score=1.0),
                   *(article(index, publisher_authority_score=0.0) for index in range(2, 5)))
    assert result.effective_publisher_count == pytest.approx(1.13125)
    assert result.publisher_authority_score == pytest.approx(1.0 / 1.13125)
    assert result.publisher_authority_score > 0.88


def test_known_authority_on_one_report_applies_to_the_same_publishers_missing_values():
    result = score(article(1, publisher_key="publisher", publisher_authority_score=0.8),
                   article(2, publisher_key="PUBLISHER"))
    assert result.publisher_authority_score == 0.8
    assert not result.publishers[0].used_fallback


def test_conflicting_values_for_one_publisher_are_rejected_instead_of_averaged_by_article_count():
    with pytest.raises(ValueError, match="conflicting authority scores for publisher: publisher"):
        score(article(1, publisher_key="publisher", publisher_authority_score=0.8),
              article(2, publisher_key="PUBLISHER", publisher_authority_score=0.2))


def test_ineligible_articles_cannot_change_authority_or_cause_conflicts():
    result = score(article(1, publisher_authority_score=0.8),
                   article(2, publisher_key="publisher-1", publisher_authority_score=0.2,
                           first_seen_at=NOW + timedelta(seconds=1)),
                   article(3, publisher_authority_score=0.0, published_at=NOW + timedelta(seconds=1)))
    assert result.publisher_authority_score == 0.8
    assert result.excluded_article_ids == (2, 3)


def test_no_eligible_or_no_weighted_publishers_produce_zero_component():
    empty = score(article(published_at=NOW + timedelta(days=1)))
    assert empty.publishers == ()
    assert empty.publisher_authority_score == empty.effective_publisher_count == 0.0
    config = RankingConfig(version="zero-v1", parameters={"coverage": {
        "unknown_publisher_weight": 0, "syndicated_publisher_weight": 0,
    }})
    zero = score_publisher_authority(cluster(article(content=None)), NOW, config)
    assert zero.publisher_authority_score == zero.effective_publisher_count == 0.0


def test_tiny_positive_coverage_weights_do_not_erase_authority():
    config = RankingConfig(version="tiny-weight-v1", parameters={"coverage": {
        "unknown_publisher_weight": 5e-324, "syndicated_publisher_weight": 0,
    }})
    result = score_publisher_authority(
        cluster(article(content=None, publisher_authority_score=0.5)), NOW, config,
    )
    assert result.effective_publisher_count > 0
    assert result.publisher_authority_score == 0.5


def test_configuration_and_inputs_are_unchanged_and_result_is_immutable():
    original = cluster(article())
    config = RankingConfig(version="custom-v1", parameters={"other": {"weight": 0.2}})
    before = original.model_dump(), config.model_dump()
    result = score_publisher_authority(original, NOW, config)
    assert (original.model_dump(), config.model_dump()) == before
    assert result.publisher_authority_score == score(article()).publisher_authority_score
    with pytest.raises(ValidationError, match="frozen"):
        result.publisher_authority_score = 0.0


def test_order_and_equivalent_timezones_do_not_change_the_result():
    reports = (article(1, publisher_authority_score=0.8), article(2, publisher_authority_score=0.6),
               article(3, content=PARAPHRASE, publisher_authority_score=0.1))
    expected = score(*reports)
    for ordering in permutations(reports):
        assert score(*ordering) == expected
    local = timezone(timedelta(hours=2))
    assert score(article()) == score(article(published_at=NOW.astimezone(local)),
                                     evaluated_at=NOW.astimezone(local))


def test_authority_component_respects_shared_coverage_configuration():
    original = cluster(article(1, publisher_authority_score=1.0), article(2, publisher_authority_score=0.0))
    config = RankingConfig(version="original-only-v1", parameters={"coverage": {"family_distribution_credit": 0}})
    result = score_publisher_authority(original, NOW, config)
    assert result.publisher_authority_score == 1.0
    assert result.publishers[1].coverage_weight == 0.0


@pytest.mark.parametrize("parameters", [
    {"unknown_authority": -0.1}, {"unknown_authority": 1.1},
    {"unknown_authority": float("nan")}, {"unknown_authority": float("inf")}, {"typo": 0.5},
])
def test_invalid_authority_policy_is_rejected(parameters):
    with pytest.raises(ValidationError):
        score(article(), **parameters)


def test_naive_evaluation_time_is_rejected():
    with pytest.raises(ValueError, match="timezone"):
        score(article(), evaluated_at=NOW.replace(tzinfo=None))

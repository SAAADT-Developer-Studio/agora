from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.ranking import (
    RankableArticle,
    RankableCluster,
    RankingComponentScores,
    RankingConfig,
    RankingFunction,
    RankingResult,
)


EVALUATED_AT = datetime(2026, 9, 13, 12, 0, tzinfo=timezone.utc)


def article(article_id: int = 1) -> RankableArticle:
    return RankableArticle(
        article_id=article_id,
        publisher_key="publisher",
        title="Article title",
        published_at=EVALUATED_AT,
    )


def components(**overrides: float) -> RankingComponentScores:
    values = {
        "coverage_score": 0.5,
        "momentum_score": 0.5,
        "freshness_score": 0.5,
        "article_contribution_score": 0.5,
        "publisher_authority_score": 0.5,
        "semantic_importance_score": 0.5,
        "cluster_confidence_score": 0.5,
    }
    values.update(overrides)
    return RankingComponentScores(**values)


def fixed_ranking_function(
    cluster: RankableCluster,
    evaluated_at: datetime,
    config: RankingConfig,
) -> RankingResult:
    return RankingResult(
        cluster_id=cluster.cluster_id,
        score=0.72,
        components=components(),
        config_version=config.version,
        evaluated_at=evaluated_at,
    )


def test_contract_models_a_complete_ranking_calculation():
    cluster = RankableCluster(cluster_id=7, articles=(article(),), category="politika")
    config = RankingConfig(
        version="formula-v1",
        parameters={"weights": {"coverage": 0.25}},
    )
    ranking_function: RankingFunction = fixed_ranking_function

    result = ranking_function(cluster, EVALUATED_AT, config)

    assert result.cluster_id == cluster.cluster_id
    assert result.config_version == config.version
    assert result.model_dump(mode="json")["evaluated_at"] == "2026-09-13T12:00:00Z"


def test_cluster_requires_at_least_one_article():
    with pytest.raises(ValidationError, match="at least 1 item"):
        RankableCluster(cluster_id=7, articles=())


def test_cluster_rejects_duplicate_article_ids():
    with pytest.raises(ValidationError, match="article IDs must be unique"):
        RankableCluster(cluster_id=7, articles=(article(), article()))


@pytest.mark.parametrize(
    ("model", "kwargs"),
    [
        (
            RankableArticle,
            {
                "article_id": 1,
                "publisher_key": "publisher",
                "title": "Title",
                "published_at": datetime(2026, 9, 13, 12, 0),
            },
        ),
        (
            RankingResult,
            {
                "cluster_id": 1,
                "score": 0.5,
                "components": components(),
                "config_version": "formula-v1",
                "evaluated_at": datetime(2026, 9, 13, 12, 0),
            },
        ),
    ],
)
def test_contract_rejects_naive_datetimes(model, kwargs):
    with pytest.raises(ValidationError, match="timezone"):
        model(**kwargs)


@pytest.mark.parametrize("invalid_score", [-0.01, 1.01, float("nan"), float("inf")])
def test_result_rejects_scores_outside_the_unit_interval(invalid_score: float):
    with pytest.raises(ValidationError):
        RankingResult(
            cluster_id=1,
            score=invalid_score,
            components=components(),
            config_version="formula-v1",
            evaluated_at=EVALUATED_AT,
        )


@pytest.mark.parametrize("invalid_score", [-0.01, 1.01, float("nan"), float("inf")])
def test_components_reject_scores_outside_the_unit_interval(invalid_score: float):
    with pytest.raises(ValidationError):
        components(coverage_score=invalid_score)


def test_contract_models_are_immutable():
    config = RankingConfig(version="formula-v1")

    with pytest.raises(ValidationError, match="frozen"):
        config.version = "formula-v2"


def test_contract_rejects_unknown_fields():
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        RankingConfig(version="formula-v1", unknown_parameter=True)

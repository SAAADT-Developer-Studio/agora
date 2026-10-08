"""Prepare source-independent authority values and score publisher authority."""

from datetime import datetime
from math import fsum
from typing import Annotated

from pydantic import AwareDatetime, Field, TypeAdapter

from app.ranking.contracts import (
    ContractModel, PublisherAuthorityProvider, RankableCluster, RankingConfig,
)
from app.ranking.coverage import score_coverage


ALGORITHM_VERSION = "publisher-authority-v1"
_AUTHORITY_VALUE = TypeAdapter(
    Annotated[float, Field(strict=True, ge=0.0, le=1.0, allow_inf_nan=False)] | None
)


class PublisherAuthorityConfig(ContractModel):
    unknown_authority: float = Field(default=0.5, ge=0.0, le=1.0)


class PublisherAuthority(ContractModel):
    publisher_key: str = Field(min_length=1)
    article_ids: tuple[int, ...] = Field(min_length=1)
    authority_score: float = Field(ge=0.0, le=1.0)
    coverage_weight: float = Field(ge=0.0, le=1.0)
    used_fallback: bool


class PublisherAuthorityResult(ContractModel):
    cluster_id: int = Field(gt=0)
    publishers: tuple[PublisherAuthority, ...]
    effective_publisher_count: float = Field(ge=0.0)
    publisher_authority_score: float = Field(ge=0.0, le=1.0)
    excluded_article_ids: tuple[int, ...]
    config_version: str
    algorithm_version: str = ALGORITHM_VERSION
    coverage_algorithm_version: str
    syndication_algorithm_version: str
    evaluated_at: AwareDatetime


def with_publisher_authority(
    cluster: RankableCluster,
    provider: PublisherAuthorityProvider,
) -> RankableCluster:
    """Return a new snapshot using one provider lookup per canonical publisher.

    This preparation step replaces existing authority values with the supplied
    provider's snapshot, including None for unknown values. The input is unchanged.
    Provider errors and invalid values propagate instead of silently becoming
    unknown. Ranking functions never call the provider themselves.
    """
    scores = {
        publisher: _AUTHORITY_VALUE.validate_python(provider.get_authority(publisher))
        for publisher in sorted({article.publisher_key.casefold() for article in cluster.articles})
    }
    # model_copy doesn't validate updates: the provider boundary above validates
    # the normalized values before they enter immutable article snapshots.
    return cluster.model_copy(update={"articles": tuple(
        article.model_copy(update={"publisher_authority_score": scores[article.publisher_key.casefold()]})
        for article in cluster.articles
    )})


def score_publisher_authority(
    cluster: RankableCluster,
    evaluated_at: datetime,
    config: RankingConfig,
) -> PublisherAuthorityResult:
    """Coverage-weighted authority, consuming only normalized snapshot values.

    Each publisher appears once. Syndication and unknown coverage use RANK-4's
    weights, and missing authority uses an explicit fallback. The origin of an
    authority value is irrelevant to this function.
    """
    policy = PublisherAuthorityConfig.model_validate(config.parameters.get("publisher_authority", {}))
    coverage = score_coverage(cluster, evaluated_at, config)
    articles = {article.article_id: article for article in cluster.articles}
    publishers = []
    for publisher in coverage.publishers:
        known = {
            articles[article_id].publisher_authority_score for article_id in publisher.article_ids
            if articles[article_id].publisher_authority_score is not None
        }
        if len(known) > 1:
            raise ValueError(f"conflicting authority scores for publisher: {publisher.publisher_key}")
        publishers.append(PublisherAuthority(
            publisher_key=publisher.publisher_key, article_ids=publisher.article_ids,
            authority_score=next(iter(known)) if known else policy.unknown_authority,
            coverage_weight=publisher.coverage_weight, used_fallback=not known,
        ))
    # Normalize weights first so very small valid coverage weights don't erase
    # authority through underflow before division by the total weight.
    score = (fsum(item.authority_score * (item.coverage_weight / coverage.effective_publisher_count)
                  for item in publishers) if coverage.effective_publisher_count else 0.0)
    return PublisherAuthorityResult(
        cluster_id=cluster.cluster_id, publishers=tuple(publishers),
        effective_publisher_count=coverage.effective_publisher_count,
        publisher_authority_score=min(1.0, max(0.0, score)),
        excluded_article_ids=coverage.excluded_article_ids,
        config_version=config.version, coverage_algorithm_version=coverage.algorithm_version,
        syndication_algorithm_version=coverage.syndication_algorithm_version,
        evaluated_at=coverage.evaluated_at,
    )

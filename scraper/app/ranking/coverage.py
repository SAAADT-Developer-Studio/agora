"""Publisher breadth with syndication discounts and diminishing returns."""

from collections import defaultdict
from datetime import datetime
from math import expm1, fsum
from typing import Literal

from pydantic import AwareDatetime, Field, model_validator

from app.ranking.contracts import ContractModel, RankableArticle, RankableCluster, RankingConfig
from app.ranking.syndication import SyndicatedFamily, detect_syndication


ALGORITHM_VERSION = "coverage-v1"
CoverageBasis = Literal["independent", "family_representative", "syndicated", "unknown"]


class CoverageConfig(ContractModel):
    """Initial policy choices; weights represent fractions of one publisher."""

    normalization_scale: float = Field(default=5.0, gt=0.0)
    unknown_publisher_weight: float = Field(default=0.5, ge=0.0, lt=1.0)
    syndicated_publisher_weight: float = Field(default=0.15, ge=0.0, lt=1.0)
    family_distribution_credit: float = Field(default=0.15, ge=0.0, lt=1.0)
    family_distribution_decay: float = Field(default=0.5, gt=0.0, lt=1.0)

    @model_validator(mode="after")
    def validate_weights(self) -> "CoverageConfig":
        if self.syndicated_publisher_weight > self.unknown_publisher_weight:
            raise ValueError("syndicated publisher weight must not exceed unknown publisher weight")
        return self


class PublisherCoverage(ContractModel):
    publisher_key: str = Field(min_length=1)
    article_ids: tuple[int, ...] = Field(min_length=1)
    basis: CoverageBasis
    coverage_weight: float = Field(ge=0.0, le=1.0)
    syndication_family_ids: tuple[str, ...] = ()


class CoverageResult(ContractModel):
    cluster_id: int = Field(gt=0)
    publishers: tuple[PublisherCoverage, ...]
    distinct_publisher_count: int = Field(ge=0)
    effective_publisher_count: float = Field(ge=0.0)
    coverage_score: float = Field(ge=0.0, le=1.0)
    syndicated_families: tuple[SyndicatedFamily, ...]
    excluded_article_ids: tuple[int, ...]
    config_version: str
    algorithm_version: str = ALGORITHM_VERSION
    syndication_algorithm_version: str
    evaluated_at: AwareDatetime


def score_coverage(
    cluster: RankableCluster,
    evaluated_at: datetime,
    config: RankingConfig,
) -> CoverageResult:
    """Score independent publisher breadth, never summing article contributions.

    RANK-3 provides the eligible articles and shared-writing families. Each
    case-insensitive publisher receives at most one unit across all its reports.
    Unknown reports cannot increase credit for a known syndicated publisher;
    genuinely independent writing can upgrade it to full credit.
    """
    policy = CoverageConfig.model_validate(config.parameters.get("coverage", {}))
    detection = detect_syndication(cluster, evaluated_at, config)
    articles = {article.article_id: article for article in cluster.articles}
    outcomes = {outcome.article_id: outcome for outcome in detection.articles}
    by_publisher: dict[str, list[RankableArticle]] = defaultdict(list)
    for outcome in detection.articles:
        article = articles[outcome.article_id]
        by_publisher[article.publisher_key.casefold()].append(article)

    representatives = {
        articles[family.representative_article_id].publisher_key.casefold()
        for family in detection.families
    }
    bases: dict[str, CoverageBasis] = {}
    weights: dict[str, float] = {}
    for publisher, reports in by_publisher.items():
        independent = any(
            outcomes[article.article_id].status == "independently_written"
            and article.is_syndicated is not True
            for article in reports
        )
        syndicated = any(
            outcomes[article.article_id].family_id is not None or article.is_syndicated is True
            for article in reports
        )
        if independent:
            bases[publisher], weights[publisher] = "independent", 1.0
        elif publisher in representatives:
            bases[publisher], weights[publisher] = "family_representative", 1.0
        elif syndicated:
            bases[publisher] = "syndicated"
            # Known syndication without a matched family gets a publisher-level
            # discount. Matched families receive their bounded allowance below.
            standalone = any(
                article.is_syndicated is True and outcomes[article.article_id].family_id is None
                for article in reports
            )
            weights[publisher] = policy.syndicated_publisher_weight if standalone else 0.0
        else:
            bases[publisher], weights[publisher] = "unknown", policy.unknown_publisher_weight

    full_credit = {
        publisher for publisher, basis in bases.items()
        if basis in ("independent", "family_representative")
    }
    for family in detection.families:
        # dict preserves each publisher's first appearance in the ordered family.
        family_publishers = dict.fromkeys(
            articles[article_id].publisher_key.casefold() for article_id in family.article_ids
        )
        additional_publishers = [
            publisher for publisher in family_publishers if publisher not in full_credit
        ]
        for ordinal, publisher in enumerate(additional_publishers):
            allowance = min(
                policy.syndicated_publisher_weight,
                policy.family_distribution_credit * (1.0 - policy.family_distribution_decay)
                * policy.family_distribution_decay ** ordinal,
            )
            # A publisher can appear in many families; repeated appearances never
            # accumulate. Publishers already earning full credit don't consume
            # distribution allowance or receive any additional credit.
            weights[publisher] = max(weights[publisher], allowance)

    publishers = tuple(
        PublisherCoverage(
            publisher_key=publisher,
            article_ids=tuple(sorted(article.article_id for article in by_publisher[publisher])),
            basis=bases[publisher],
            coverage_weight=weights[publisher],
            syndication_family_ids=tuple(sorted({
                outcomes[article.article_id].family_id
                for article in by_publisher[publisher]
                if outcomes[article.article_id].family_id is not None
            })),
        )
        for publisher in sorted(by_publisher)
    )
    effective_count = fsum(publisher.coverage_weight for publisher in publishers)
    return CoverageResult(
        cluster_id=cluster.cluster_id, publishers=publishers,
        distinct_publisher_count=len(publishers), effective_publisher_count=effective_count,
        coverage_score=min(1.0, max(0.0, -expm1(-effective_count / policy.normalization_scale))),
        syndicated_families=detection.families,
        excluded_article_ids=detection.excluded_article_ids,
        config_version=config.version, syndication_algorithm_version=detection.algorithm_version,
        evaluated_at=detection.evaluated_at,
    )

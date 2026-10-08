"""Compose independently bounded ranking signals with one freshness/confidence gate."""

from datetime import datetime
from math import fsum
from typing import Literal

from pydantic import Field, model_validator

from app.ranking.article_contribution import ArticleContributionResult, score_article_contribution
from app.ranking.cluster_confidence import (
    ClusterConfidenceResult, finalize_ranking, score_cluster_confidence,
)
from app.ranking.contracts import (
    ContractModel, RankableCluster, RankingComponentScores, RankingConfig, RankingResult,
)
from app.ranking.coverage import CoverageResult, score_coverage
from app.ranking.freshness import FreshnessResult, score_freshness
from app.ranking.momentum import MomentumResult, score_momentum
from app.ranking.newsworthiness import NewsworthinessResult, score_newsworthiness
from app.ranking.publisher_authority import PublisherAuthorityResult, score_publisher_authority


ALGORITHM_VERSION = "cluster-ranking-v1"


def _normalized_weights(weights: tuple[float, ...]) -> tuple[float, ...]:
    """Normalize configuration constants safely, never a population of clusters."""
    scale = max(weights)
    if scale == 0.0:
        return tuple(0.0 for _ in weights)
    scaled = tuple(weight / scale for weight in weights)
    total = fsum(scaled)
    return tuple(weight / total for weight in scaled)


class ArticleStrengthConfig(ContractModel):
    """Intrinsic contribution factors for composition; no age or volume terms."""

    authority_weight: float = Field(default=0.5, ge=0.0)
    data_quality_weight: float = Field(default=0.3, ge=0.0)
    source_weight: float = Field(default=0.2, ge=0.0)

    @model_validator(mode="after")
    def positive_weight(self) -> "ArticleStrengthConfig":
        if not any(self.weights):
            raise ValueError("at least one article-strength weight must be positive")
        return self

    @property
    def weights(self) -> tuple[float, ...]:
        return (self.authority_weight, self.data_quality_weight, self.source_weight)


class ClusterRankingConfig(ContractModel):
    """Equal initial base weights; calibration can change config without changing the engine."""

    article_contribution_weight: float = Field(default=1.0, ge=0.0)
    coverage_weight: float = Field(default=1.0, ge=0.0)
    momentum_weight: float = Field(default=1.0, ge=0.0)
    semantic_importance_weight: float = Field(default=1.0, ge=0.0)
    article_strength: ArticleStrengthConfig = Field(default_factory=ArticleStrengthConfig)

    @model_validator(mode="after")
    def positive_weight(self) -> "ClusterRankingConfig":
        if not any(self.weights):
            raise ValueError("at least one base-score weight must be positive")
        return self

    @property
    def weights(self) -> tuple[float, ...]:
        return (self.article_contribution_weight, self.coverage_weight,
                self.momentum_weight, self.semantic_importance_weight)


class PublisherArticleStrength(ContractModel):
    publisher_key: str = Field(min_length=1)
    article_id: int = Field(gt=0)
    data_quality: float = Field(ge=0.0, le=1.0)
    source_credit: float = Field(ge=0.0, le=1.0)
    selection_score: float = Field(ge=0.0, le=1.0)
    used_unknown_content: bool


class ArticleStrengthResult(ContractModel):
    article_contribution_score: float = Field(ge=0.0, le=1.0)
    publisher_authority_score: float = Field(ge=0.0, le=1.0)
    mean_data_quality: float = Field(ge=0.0, le=1.0)
    mean_source_credit: float = Field(ge=0.0, le=1.0)
    authority_weight: float = Field(ge=0.0, le=1.0)
    data_quality_weight: float = Field(ge=0.0, le=1.0)
    source_weight: float = Field(ge=0.0, le=1.0)
    publishers: tuple[PublisherArticleStrength, ...]
    basis: Literal["available", "no_qualifying_reports", "unavailable"]


class WeightedRankingTerm(ContractModel):
    component: Literal[
        "article_contribution_score", "coverage_score", "momentum_score", "semantic_importance_score",
    ]
    score: float = Field(ge=0.0, le=1.0)
    weight: float = Field(ge=0.0, le=1.0)
    weighted_score: float = Field(ge=0.0, le=1.0)


class ClusterRankingExplanation(ContractModel):
    result: RankingResult
    base_score: float = Field(ge=0.0, le=1.0)
    terms: tuple[WeightedRankingTerm, ...]
    freshness_factor: float = Field(ge=0.0, le=1.0)
    confidence_factor: float = Field(ge=0.0, le=1.0)
    article_strength: ArticleStrengthResult
    article_contribution: ArticleContributionResult
    coverage: CoverageResult
    momentum: MomentumResult
    newsworthiness: NewsworthinessResult
    publisher_authority: PublisherAuthorityResult
    freshness: FreshnessResult
    confidence: ClusterConfidenceResult
    algorithm_version: str = ALGORITHM_VERSION


def _article_strength(
    cluster: RankableCluster, contribution: ArticleContributionResult,
    authority: PublisherAuthorityResult, policy: ArticleStrengthConfig,
) -> ArticleStrengthResult:
    """Project RANK-2's quality/source diagnostics without its age/count/novelty bonuses.

    A family supplies its representative once; each publisher supplies its best
    quality/source report. Authority comes from RANK-5 once, within this term.
    """
    articles = {article.article_id: article for article in cluster.articles}
    selection_weights = _normalized_weights((policy.data_quality_weight, policy.source_weight))
    by_publisher: dict[str, PublisherArticleStrength] = {}
    for item in contribution.articles:
        if item.syndication_family_id is not None:
            if item.family_representative_article_id != item.article_id:
                continue
        elif articles[item.article_id].is_syndicated is True:
            continue
        publisher = item.publisher_key.casefold()
        selection_score = min(1.0, fsum((item.data_quality * selection_weights[0],
                                        item.source_credit * selection_weights[1])))
        previous = by_publisher.get(publisher)
        # Contributions are chronological, so ties keep the earlier report.
        if previous is None or selection_score > previous.selection_score:
            by_publisher[publisher] = PublisherArticleStrength(
                publisher_key=publisher, article_id=item.article_id,
                data_quality=item.data_quality, source_credit=item.source_credit,
                selection_score=selection_score, used_unknown_content=item.syndication_status == "unknown",
            )
    publishers = tuple(by_publisher[key] for key in sorted(by_publisher))
    quality = fsum(item.data_quality / len(publishers) for item in publishers) if publishers else 0.0
    source = fsum(item.source_credit / len(publishers) for item in publishers) if publishers else 0.0
    weights = _normalized_weights(policy.weights)
    value = (fsum((authority.publisher_authority_score * weights[0],
                   quality * weights[1], source * weights[2])) if publishers else 0.0)
    return ArticleStrengthResult(
        article_contribution_score=min(1.0, max(0.0, value)),
        publisher_authority_score=authority.publisher_authority_score,
        mean_data_quality=min(1.0, quality), mean_source_credit=min(1.0, source),
        authority_weight=weights[0], data_quality_weight=weights[1], source_weight=weights[2],
        publishers=publishers,
        basis="available" if publishers else "no_qualifying_reports" if contribution.articles else "unavailable",
    )


def explain_cluster_ranking(
    cluster: RankableCluster, evaluated_at: datetime, config: RankingConfig,
) -> ClusterRankingExplanation:
    """Compose one snapshot and retain every term, gate, and component fallback.

    Coverage owns accumulated breadth. Momentum owns recent velocity/change.
    Semantic importance owns LLM judgments. Article strength owns authority,
    quality, and source credit. Freshness and confidence are applied only at
    finalization, never as additional positive terms or per-article decay.
    """
    policy = ClusterRankingConfig.model_validate(config.parameters.get("ranking", {}))
    contribution = score_article_contribution(cluster, evaluated_at, config)
    coverage = score_coverage(cluster, evaluated_at, config)
    authority = score_publisher_authority(cluster, evaluated_at, config)
    momentum = score_momentum(cluster, evaluated_at, config)
    newsworthiness = score_newsworthiness(cluster, evaluated_at, config)
    freshness = score_freshness(cluster, evaluated_at, config)
    confidence = score_cluster_confidence(cluster, evaluated_at, config)
    strength = _article_strength(cluster, contribution, authority, policy.article_strength)
    components = RankingComponentScores(
        article_contribution_score=strength.article_contribution_score,
        coverage_score=coverage.coverage_score,
        momentum_score=momentum.momentum_score,
        semantic_importance_score=newsworthiness.semantic_importance_score,
        publisher_authority_score=authority.publisher_authority_score,
        freshness_score=freshness.freshness_score,
        cluster_confidence_score=confidence.cluster_confidence_score,
    )
    names = ("article_contribution_score", "coverage_score", "momentum_score", "semantic_importance_score")
    terms = tuple(WeightedRankingTerm(
        component=name, score=getattr(components, name), weight=weight,
        weighted_score=getattr(components, name) * weight,
    ) for name, weight in zip(names, _normalized_weights(policy.weights), strict=True))
    base = min(1.0, max(0.0, fsum(term.weighted_score for term in terms)))
    result = finalize_ranking(
        cluster_id=cluster.cluster_id, base_score=base, components=components,
        evaluated_at=contribution.evaluated_at, config=config,
    )
    return ClusterRankingExplanation(
        result=result, base_score=base, terms=terms,
        freshness_factor=freshness.freshness_score, confidence_factor=confidence.gate_multiplier,
        article_strength=strength, article_contribution=contribution,
        coverage=coverage, momentum=momentum, newsworthiness=newsworthiness,
        publisher_authority=authority, freshness=freshness, confidence=confidence,
    )


def rank_cluster(
    cluster: RankableCluster, evaluated_at: datetime, config: RankingConfig,
) -> RankingResult:
    """RankingFunction implementation: a bounded, local, pure event score."""
    return explain_cluster_ranking(cluster, evaluated_at, config).result

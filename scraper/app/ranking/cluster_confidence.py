"""Measure event coherence and gate ranking scores with cluster confidence."""

from collections import Counter
from datetime import datetime, timezone
from math import fsum, isfinite, sqrt
from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, TypeAdapter, model_validator

from app.ranking.contracts import (
    ContractModel, RankableCluster, RankingComponentScores, RankingConfig, RankingResult,
)
from app.ranking.syndication import detect_syndication


ALGORITHM_VERSION = "cluster-confidence-v1"
_UNIT_SCORE = TypeAdapter(Annotated[float, Field(strict=True, ge=0.0, le=1.0, allow_inf_nan=False)])


class ClusterConfidenceConfig(ContractModel):
    """Initial coherence thresholds; confidence is a multiplier, never a count bonus."""

    outlier_similarity: float = Field(default=0.4, ge=-1.0, lt=1.0)
    weak_similarity: float = Field(default=0.75, gt=-1.0, lt=1.0)
    strong_similarity: float = Field(default=0.9, gt=-1.0, le=1.0)
    outlier_membership: float = Field(default=0.2, ge=0.0, lt=1.0)
    weak_membership: float = Field(default=0.5, gt=0.0, le=1.0)
    semantic_weight: float = Field(default=0.7, ge=0.0, le=1.0)
    unknown_similarity_score: float = Field(default=0.5, ge=0.0, lt=1.0)
    unknown_membership_confidence: float = Field(default=0.5, ge=0.0, lt=1.0)
    weak_relation_penalty: float = Field(default=0.5, ge=0.0, le=1.0)
    temporal_half_life_hours: float = Field(default=72.0, gt=0.0)
    temporal_penalty: float = Field(default=0.25, ge=0.0, le=1.0)
    gate_power: float = Field(default=2.0, ge=1.0)

    @model_validator(mode="after")
    def ordered_thresholds(self) -> "ClusterConfidenceConfig":
        if not self.outlier_similarity < self.weak_similarity < self.strong_similarity:
            raise ValueError("similarity thresholds must satisfy outlier < weak < strong")
        if self.outlier_membership >= self.weak_membership:
            raise ValueError("membership thresholds must satisfy outlier < weak")
        return self


class ConfidenceReport(ContractModel):
    representative_article_id: int = Field(gt=0)
    article_ids: tuple[int, ...] = Field(min_length=1)
    publisher_key: str = Field(min_length=1)
    syndication_family_id: str | None = None
    weight: float = Field(gt=0.0, le=1.0)
    embedding_status: Literal[
        "missing", "zero_vector", "incompatible_dimension", "no_peers",
        "cancelled_peer_centroid", "compared",
    ]
    peer_centroid_similarity: float | None = Field(default=None, ge=-1.0, le=1.0)
    similarity_score: float = Field(ge=0.0, le=1.0)
    membership_confidence: float = Field(ge=0.0, le=1.0)
    used_semantic_fallback: bool
    used_membership_fallback: bool
    is_outlier: bool
    is_weakly_related: bool
    temporal_deviation_hours: float = Field(ge=0.0)


class ClusterConfidenceResult(ContractModel):
    cluster_id: int = Field(gt=0)
    cluster_confidence_score: float = Field(ge=0.0, le=1.0)
    gate_multiplier: float = Field(ge=0.0, le=1.0)
    basis: Literal["measured", "fallback", "unavailable"]
    embedding_dimension: int | None = Field(default=None, gt=0)
    compared_report_count: int = Field(ge=0)
    effective_report_weight: float = Field(ge=0.0)
    semantic_data_fraction: float = Field(ge=0.0, le=1.0)
    membership_data_fraction: float = Field(ge=0.0, le=1.0)
    semantic_coherence_score: float = Field(ge=0.0, le=1.0)
    membership_confidence_score: float = Field(ge=0.0, le=1.0)
    signal_confidence_score: float = Field(ge=0.0, le=1.0)
    outlier_proportion: float = Field(ge=0.0, le=1.0)
    weakly_related_proportion: float = Field(ge=0.0, le=1.0)
    temporal_coherence_score: float = Field(ge=0.0, le=1.0)
    temporal_center_at: AwareDatetime | None
    mean_temporal_deviation_hours: float | None = Field(default=None, ge=0.0)
    reports: tuple[ConfidenceReport, ...]
    excluded_article_ids: tuple[int, ...]
    config_version: str
    algorithm_version: str = ALGORITHM_VERSION
    syndication_algorithm_version: str
    evaluated_at: AwareDatetime


def _unit(value: float) -> float:
    return min(1.0, max(0.0, value))


def _normalize(vector: tuple[float, ...]) -> tuple[float, ...] | None:
    if not vector or not all(isfinite(value) for value in vector):
        return None
    scale = max(abs(value) for value in vector)
    if scale == 0.0:
        return None
    scaled = tuple(value / scale for value in vector)
    length = sqrt(fsum(value * value for value in scaled))
    return tuple(value / length for value in scaled)


def score_cluster_confidence(
    cluster: RankableCluster, evaluated_at: datetime, config: RankingConfig,
) -> ClusterConfidenceResult:
    """Estimate coherence from peers, membership, relation failures, and time spread.

    Each syndicated family uses its representative's signals once. Each publisher
    has total weight one, shared across its remaining reports. Missing signals
    stay visible and cannot silently become perfect confidence.
    """
    policy = ClusterConfidenceConfig.model_validate(config.parameters.get("cluster_confidence", {}))
    detection = detect_syndication(cluster, evaluated_at, config)
    articles = {article.article_id: article for article in cluster.articles}
    families = {family.family_id: family for family in detection.families}
    outcomes = [outcome for outcome in detection.articles
                if outcome.family_id is None or outcome.representative_article_id == outcome.article_id]
    representatives = [articles[outcome.article_id] for outcome in outcomes]
    publisher_counts = Counter(article.publisher_key.casefold() for article in representatives)
    weights = [1.0 / publisher_counts[article.publisher_key.casefold()] for article in representatives]
    total_weight = fsum(weights)
    vectors = [_normalize(article.embedding) for article in representatives]
    # Mixed dimensions are not compared. Pick the dimension with most balanced
    # publisher support; ties use the smaller dimension, not input tuple order.
    dimensions = sorted({len(vector) for vector in vectors if vector is not None})
    dimension = max(dimensions, key=lambda size: (
        fsum(weight for vector, weight in zip(vectors, weights, strict=True)
             if vector is not None and len(vector) == size), -size,
    ), default=None)
    comparable = [index for index, vector in enumerate(vectors)
                  if vector is not None and len(vector) == dimension]
    vector_total = tuple(fsum(weights[index] * vectors[index][axis] for index in comparable)
                         for axis in range(dimension or 0))
    vector_weight = fsum(weights[index] for index in comparable)

    center = None
    cumulative = 0.0
    # Representatives already follow UTC publication order from detection.
    for article, weight in zip(representatives, weights, strict=True):
        cumulative += weight
        if cumulative >= total_weight / 2.0:
            center = article.published_at.astimezone(timezone.utc)
            break
    reports = []
    for article, outcome, weight, vector in zip(
        representatives, outcomes, weights, vectors, strict=True,
    ):
        similarity = None
        semantic_fallback = True
        similarity_score = policy.unknown_similarity_score
        semantic_outlier = semantic_weak = False
        if not article.embedding:
            status = "missing"
        elif vector is None:
            status = "zero_vector"
        elif len(vector) != dimension:
            status = "incompatible_dimension"
        elif len(comparable) < 2:
            status = "no_peers"
        else:
            # Leave this report out: its own vector must not manufacture a
            # strong article-to-centroid match, especially for tiny clusters.
            peer_total = tuple(total - weight * value
                               for total, value in zip(vector_total, vector, strict=True))
            peer_length = sqrt(fsum(value * value for value in peer_total))
            semantic_fallback = False
            if peer_length <= 1e-12 * (vector_weight - weight):
                # Several available peer directions cancel: this is incoherence,
                # distinct from missing data or a singleton's absent comparison.
                status, similarity_score = "cancelled_peer_centroid", 0.0
                semantic_outlier = semantic_weak = True
            else:
                status = "compared"
                similarity = max(-1.0, min(1.0, fsum(
                    value * (peer / peer_length)
                    for value, peer in zip(vector, peer_total, strict=True)
                )))
                similarity_score = _unit((similarity - policy.outlier_similarity)
                                         / (policy.strong_similarity - policy.outlier_similarity))
                semantic_outlier = similarity < policy.outlier_similarity
                semantic_weak = similarity < policy.weak_similarity
        membership = article.cluster_membership_confidence
        membership_fallback = membership is None
        membership_outlier = membership is not None and membership < policy.outlier_membership
        membership_weak = membership is not None and membership < policy.weak_membership
        family = families.get(outcome.family_id)
        reports.append(ConfidenceReport(
            representative_article_id=article.article_id,
            article_ids=family.article_ids if family is not None else (article.article_id,),
            publisher_key=article.publisher_key.casefold(), syndication_family_id=outcome.family_id,
            weight=weight, embedding_status=status, peer_centroid_similarity=similarity,
            similarity_score=similarity_score,
            membership_confidence=policy.unknown_membership_confidence if membership is None else membership,
            used_semantic_fallback=semantic_fallback, used_membership_fallback=membership_fallback,
            is_outlier=semantic_outlier or membership_outlier,
            is_weakly_related=semantic_weak or membership_weak,
            temporal_deviation_hours=abs((article.published_at.astimezone(timezone.utc) - center).total_seconds()) / 3600.0,
        ))

    def mean(values: list[float]) -> float:
        return fsum(value * (weight / total_weight)
                    for value, weight in zip(values, weights, strict=True)) if total_weight else 0.0

    semantic_score = _unit(mean([report.similarity_score for report in reports]))
    membership_score = _unit(mean([report.membership_confidence for report in reports]))
    outliers = _unit(mean([float(report.is_outlier) for report in reports]))
    weak = _unit(mean([float(report.is_weakly_related) for report in reports]))
    semantic_fraction = _unit(mean([float(not report.used_semantic_fallback) for report in reports]))
    membership_fraction = _unit(mean([float(not report.used_membership_fallback) for report in reports]))
    deviation = mean([report.temporal_deviation_hours for report in reports]) if reports else None
    temporal = 2.0 ** (-deviation / policy.temporal_half_life_hours) if deviation is not None else 0.0
    signal = policy.semantic_weight * semantic_score + (1.0 - policy.semantic_weight) * membership_score
    confidence = _unit(signal * (1.0 - outliers) * (1.0 - policy.weak_relation_penalty * weak)
                       * (1.0 - policy.temporal_penalty * (1.0 - temporal)))
    return ClusterConfidenceResult(
        cluster_id=cluster.cluster_id, cluster_confidence_score=confidence,
        gate_multiplier=confidence ** policy.gate_power,
        basis="measured" if semantic_fraction or membership_fraction else "fallback" if reports else "unavailable",
        embedding_dimension=dimension, compared_report_count=sum(not report.used_semantic_fallback for report in reports),
        effective_report_weight=total_weight, semantic_data_fraction=semantic_fraction,
        membership_data_fraction=membership_fraction, semantic_coherence_score=semantic_score,
        membership_confidence_score=membership_score, signal_confidence_score=signal,
        outlier_proportion=outliers, weakly_related_proportion=weak,
        temporal_coherence_score=temporal, temporal_center_at=center,
        mean_temporal_deviation_hours=deviation, reports=tuple(reports),
        excluded_article_ids=detection.excluded_article_ids,
        config_version=config.version, syndication_algorithm_version=detection.algorithm_version,
        evaluated_at=detection.evaluated_at,
    )


def apply_confidence_gate(
    base_score: float, cluster_confidence_score: float, config: RankingConfig,
) -> float:
    """Gate a normalized base score; increasing volume cannot exceed this ceiling."""
    base = _UNIT_SCORE.validate_python(base_score)
    confidence = _UNIT_SCORE.validate_python(cluster_confidence_score)
    policy = ClusterConfidenceConfig.model_validate(config.parameters.get("cluster_confidence", {}))
    return base * confidence ** policy.gate_power


def finalize_ranking(
    *, cluster_id: int, base_score: float, components: RankingComponentScores,
    evaluated_at: datetime, config: RankingConfig,
) -> RankingResult:
    """Apply event freshness and confidence once to a normalized combined score.

    The caller supplies its base formula before either gate. Neither freshness
    nor confidence belongs in that positive additive component sum.
    """
    if evaluated_at.tzinfo is None or evaluated_at.utcoffset() is None:
        raise ValueError("evaluated_at must have a timezone")
    base = _UNIT_SCORE.validate_python(base_score)
    return RankingResult(
        cluster_id=cluster_id,
        score=apply_confidence_gate(base * components.freshness_score, components.cluster_confidence_score, config),
        components=components, config_version=config.version,
        evaluated_at=evaluated_at.astimezone(timezone.utc),
    )

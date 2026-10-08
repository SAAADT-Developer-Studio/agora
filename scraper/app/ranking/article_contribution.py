"""Pure, explainable article contributions within one event cluster."""

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from math import expm1, fsum, isfinite, sqrt
import re
import unicodedata

from pydantic import AwareDatetime, Field, model_validator

from app.ranking.contracts import ContractModel, RankableArticle, RankableCluster, RankingConfig
from app.ranking.syndication import (
    ArticleSyndication, SyndicatedFamily, SyndicationStatus, detect_syndication,
)


ALGORITHM_VERSION = "article-contribution-v2"


class ArticleContributionConfig(ContractModel):
    """Defaults are initial policy choices, not empirically calibrated weights."""

    authority_weight: float = Field(default=0.25, ge=0.0, le=1.0)
    originality_weight: float = Field(default=0.20, ge=0.0, le=1.0)
    novelty_weight: float = Field(default=0.30, ge=0.0, le=1.0)
    quality_weight: float = Field(default=0.15, ge=0.0, le=1.0)
    source_weight: float = Field(default=0.10, ge=0.0, le=1.0)
    freshness_half_life_hours: float = Field(default=24.0, gt=0.0)
    publisher_repeat_decay: float = Field(default=0.5, gt=0.0, lt=1.0)
    normalization_scale: float = Field(default=3.0, gt=0.0)
    unknown_authority: float = Field(default=0.5, ge=0.0, le=1.0)
    unknown_originality: float = Field(default=0.5, ge=0.0, le=1.0)
    unknown_novelty: float = Field(default=0.5, ge=0.0, le=1.0)
    unknown_source_credit: float = Field(default=0.25, ge=0.0, le=1.0)
    unknown_syndication_multiplier: float = Field(default=0.85, gt=0.0, lt=1.0)
    syndication_multiplier: float = Field(default=0.35, ge=0.0, lt=1.0)
    syndicated_originality_cap: float = Field(default=0.15, ge=0.0, le=1.0)
    family_distribution_credit: float = Field(default=0.15, ge=0.0, lt=1.0)
    family_distribution_decay: float = Field(default=0.5, gt=0.0, lt=1.0)
    breaking_credit: float = Field(default=0.75, ge=0.0, le=1.0)
    semantic_novelty_weight: float = Field(default=0.70, ge=0.0, le=1.0)
    novelty_similarity_floor: float = Field(default=0.70, ge=0.0, lt=1.0)
    redundancy_similarity: float = Field(default=0.98, gt=0.0, le=1.0)
    minimum_text_tokens: int = Field(default=12, ge=5)
    full_content_tokens: int = Field(default=200, ge=1)
    full_summary_tokens: int = Field(default=40, ge=1)

    @model_validator(mode="after")
    def validate_policy(self) -> "ArticleContributionConfig":
        if self.weight_total == 0:
            raise ValueError("at least one contribution weight must be positive")
        if self.redundancy_similarity <= self.novelty_similarity_floor:
            raise ValueError("redundancy_similarity must exceed novelty_similarity_floor")
        if self.syndication_multiplier > self.unknown_syndication_multiplier:
            raise ValueError("known syndication must not contribute more than unknown syndication")
        return self

    @property
    def weight_total(self) -> float:
        return fsum((self.authority_weight, self.originality_weight, self.novelty_weight,
                     self.quality_weight, self.source_weight))


class ArticleContribution(ContractModel):
    article_id: int = Field(gt=0)
    publisher_key: str
    publisher_ordinal: int = Field(ge=1)
    compared_article_count: int = Field(ge=0)
    publisher_authority: float = Field(ge=0.0, le=1.0)
    originality: float = Field(ge=0.0, le=1.0)
    syndication_multiplier: float = Field(ge=0.0, le=1.0)
    syndication_status: SyndicationStatus
    syndication_family_id: str | None = None
    family_representative_article_id: int | None = Field(default=None, gt=0)
    family_multiplier: float = Field(default=1.0, ge=0.0, le=1.0)
    freshness: float = Field(ge=0.0, le=1.0)
    source_credit: float = Field(ge=0.0, le=1.0)
    data_quality: float = Field(ge=0.0, le=1.0)
    novelty: float = Field(ge=0.0, le=1.0)
    publisher_multiplier: float = Field(ge=0.0, le=1.0)
    base_contribution: float = Field(ge=0.0, le=1.0)
    contribution: float = Field(ge=0.0, le=1.0)
    max_text_reuse: float | None = Field(default=None, ge=0.0, le=1.0)
    new_text_fraction: float | None = Field(default=None, ge=0.0, le=1.0)
    max_semantic_similarity: float | None = Field(default=None, ge=-1.0, le=1.0)
    fallback_signals: tuple[str, ...] = ()


class ArticleContributionResult(ContractModel):
    cluster_id: int = Field(gt=0)
    articles: tuple[ArticleContribution, ...]
    syndicated_families: tuple[SyndicatedFamily, ...]
    syndication_algorithm_version: str
    excluded_article_ids: tuple[int, ...]
    total_contribution: float = Field(ge=0.0)
    article_contribution_score: float = Field(ge=0.0, le=1.0)
    config_version: str
    algorithm_version: str = ALGORITHM_VERSION
    evaluated_at: AwareDatetime


@dataclass(frozen=True)
class _PreparedArticle:
    article: RankableArticle
    content_tokens: tuple[str, ...]
    summary_tokens: tuple[str, ...]
    body_shingles: frozenset[tuple[str, ...]]
    comparison_shingles: frozenset[tuple[str, ...]]
    vector: tuple[float, ...] | None


def _unit(value: float) -> float:
    return min(1.0, max(0.0, value))


def _tokens(value: str | None) -> tuple[str, ...]:
    return tuple(re.findall(r"\w+", unicodedata.normalize("NFKC", value or "").casefold()))


def _shingles(tokens: tuple[str, ...], minimum: int) -> frozenset[tuple[str, ...]]:
    if len(tokens) < minimum:
        return frozenset()
    return frozenset(tokens[i:i + 5] for i in range(len(tokens) - 4))


def _normalized_vector(vector: tuple[float, ...]) -> tuple[float, ...] | None:
    if not vector or not all(isfinite(value) for value in vector):
        return None
    scale = max(abs(value) for value in vector)
    if scale == 0:
        return None
    scaled = tuple(value / scale for value in vector)
    length = sqrt(fsum(value * value for value in scaled))
    return tuple(value / length for value in scaled)


def _prepare(article: RankableArticle, policy: ArticleContributionConfig) -> _PreparedArticle:
    content, summary = _tokens(article.content), _tokens(article.summary)
    body = _shingles(content, policy.minimum_text_tokens)
    return _PreparedArticle(article, content, summary, body,
                            body or _shingles(summary, policy.minimum_text_tokens),
                            _normalized_vector(article.embedding))


def _novelty(
    current: _PreparedArticle,
    earlier: list[_PreparedArticle],
    known_shingles: set[tuple[str, ...]],
    policy: ArticleContributionConfig,
) -> tuple[float, float | None, float | None, bool, float | None]:
    """Return novelty, body reuse, semantic similarity, fallback flag, and new text fraction."""
    reuse = max((len(current.body_shingles & old.body_shingles) / len(current.body_shingles)
                 for old in earlier if current.body_shingles and old.body_shingles), default=None)
    similarity = max((fsum(a * b for a, b in zip(current.vector, old.vector, strict=True))
                      for old in earlier if current.vector and old.vector
                      and len(current.vector) == len(old.vector)), default=None)
    if similarity is not None:
        similarity = max(-1.0, min(1.0, similarity))
    if not earlier and (current.comparison_shingles or current.vector):
        return 1.0, reuse, similarity, False, 1.0 if current.comparison_shingles else None
    # Complete reuse across several reports is also redundant (e.g. a compilation).
    lexical = (1.0 - len(current.comparison_shingles & known_shingles) / len(current.comparison_shingles)
               if current.comparison_shingles and known_shingles else None)
    if lexical == 0.0:
        return 0.0, reuse, similarity, False, lexical
    semantic = (_unit((policy.redundancy_similarity - similarity)
                      / (policy.redundancy_similarity - policy.novelty_similarity_floor))
                if similarity is not None else None)
    if lexical is not None and semantic is not None:
        score = lexical * (1.0 - policy.semantic_novelty_weight) + semantic * policy.semantic_novelty_weight
    else:
        score = lexical if lexical is not None else semantic
    return ((policy.unknown_novelty if score is None else _unit(score)),
            reuse, similarity, score is None, lexical)


def _score_article(
    current: _PreparedArticle,
    earlier: list[_PreparedArticle],
    known_shingles: set[tuple[str, ...]],
    publisher_ordinal: int,
    first_published_at: datetime,
    evaluated_at: datetime,
    policy: ArticleContributionConfig,
    detection: ArticleSyndication,
) -> ArticleContribution:
    article = current.article
    fallback = []
    authority = article.publisher_authority_score
    if authority is None:
        authority = policy.unknown_authority
        fallback.append("publisher_authority")
    novelty, reuse, similarity, novelty_fallback, new_text_fraction = _novelty(
        current, earlier, known_shingles, policy,
    )
    if novelty_fallback:
        fallback.append("novelty")
    originality = article.originality_score
    if originality is None:
        if detection.originality_score is None:
            originality = policy.unknown_originality
            fallback.append("originality")
        else:
            originality = detection.originality_score
    representative = detection.representative_article_id == article.article_id
    if representative:
        # Count the family's writing once, even if the original publisher isn't
        # in the snapshot and every observed copy has an upstream syndication flag.
        syndication = 1.0
    elif detection.family_id is not None or article.is_syndicated is True:
        syndication = policy.syndication_multiplier
        originality = min(originality, policy.syndicated_originality_cap)
    elif detection.status == "independently_written" or article.is_syndicated is False:
        syndication = 1.0
    else:
        syndication = policy.unknown_syndication_multiplier
        fallback.append("syndication")
    if article.is_primary_source is None:
        source = policy.unknown_source_credit
        fallback.append("primary_source")
    else:
        source = float(article.is_primary_source)
    published_at = article.published_at.astimezone(timezone.utc)
    if published_at == first_published_at:
        source = max(source, policy.breaking_credit)
    quality = _unit(fsum((
        0.20,
        0.50 * min(len(current.content_tokens) / policy.full_content_tokens, 1.0),
        0.20 * min(len(current.summary_tokens) / policy.full_summary_tokens, 1.0),
        0.10 * (current.vector is not None),
    )))
    age_hours = (evaluated_at - published_at).total_seconds() / 3600.0
    freshness = 2.0 ** (-age_hours / policy.freshness_half_life_hours)
    publisher_multiplier = policy.publisher_repeat_decay ** (publisher_ordinal - 1)
    base = _unit(fsum((authority * policy.authority_weight, originality * policy.originality_weight,
                      novelty * policy.novelty_weight, quality * policy.quality_weight,
                      source * policy.source_weight)) / policy.weight_total)
    return ArticleContribution(
        article_id=article.article_id, publisher_key=article.publisher_key,
        publisher_ordinal=publisher_ordinal, compared_article_count=len(earlier),
        publisher_authority=authority, originality=originality, syndication_multiplier=syndication,
        syndication_status=detection.status, syndication_family_id=detection.family_id,
        family_representative_article_id=detection.representative_article_id,
        freshness=freshness, source_credit=source, data_quality=quality, novelty=novelty,
        publisher_multiplier=publisher_multiplier, base_contribution=base,
        contribution=_unit(base * syndication * freshness * publisher_multiplier),
        max_text_reuse=reuse, max_semantic_similarity=similarity, fallback_signals=tuple(fallback),
        new_text_fraction=new_text_fraction,
    )


def _apply_family_credit(
    contributions: list[ArticleContribution],
    families: tuple[SyndicatedFamily, ...],
    policy: ArticleContributionConfig,
) -> list[ArticleContribution]:
    """Bound extra distribution credit across publishers, regardless of copy count."""
    by_id = {item.article_id: item for item in contributions}
    for family in families:
        representative = by_id[family.representative_article_id]
        publishers = {representative.publisher_key.casefold()}
        distribution_ordinal = 0
        for article_id in family.article_ids[1:]:
            item = by_id[article_id]
            publisher = item.publisher_key.casefold()
            allowance = 0.0
            if publisher not in publishers:
                publishers.add(publisher)
                allowance = (representative.contribution * policy.family_distribution_credit
                             * (1.0 - policy.family_distribution_decay)
                             * policy.family_distribution_decay ** distribution_ordinal)
                distribution_ordinal += 1
            credited = min(item.contribution, allowance)
            multiplier = credited / item.contribution if item.contribution else 0.0
            by_id[article_id] = item.model_copy(update={
                "contribution": credited, "family_multiplier": multiplier,
            })
    return [by_id[item.article_id] for item in contributions]


def score_article_contribution(
    cluster: RankableCluster,
    evaluated_at: datetime,
    config: RankingConfig,
) -> ArticleContributionResult:
    """Score a snapshot without I/O, input mutation, or cross-cluster normalization.

    Only articles published and (when known) first seen by evaluated_at are eligible.
    Ties use first-seen time and article ID so input tuple order cannot affect scores.
    """
    if evaluated_at.tzinfo is None or evaluated_at.utcoffset() is None:
        raise ValueError("evaluated_at must have a timezone")
    evaluated_at = evaluated_at.astimezone(timezone.utc)
    policy = ArticleContributionConfig.model_validate(config.parameters.get("article_contribution", {}))
    detection = detect_syndication(cluster, evaluated_at, config)
    outcomes = {item.article_id: item for item in detection.articles}
    articles_by_id = {article.article_id: article for article in cluster.articles}
    eligible = [articles_by_id[item.article_id] for item in detection.articles]
    contributions = []
    earlier: list[_PreparedArticle] = []
    known_shingles: set[tuple[str, ...]] = set()
    publisher_counts: Counter[str] = Counter()
    for article in eligible:
        publisher = article.publisher_key.casefold()
        publisher_counts[publisher] += 1
        current = _prepare(article, policy)
        contributions.append(_score_article(current, earlier, known_shingles, publisher_counts[publisher],
                                       eligible[0].published_at.astimezone(timezone.utc), evaluated_at,
                                       policy, outcomes[article.article_id]))
        earlier.append(current)
        known_shingles.update(current.comparison_shingles)
    contributions = _apply_family_credit(contributions, detection.families, policy)
    total = fsum(item.contribution for item in contributions)
    return ArticleContributionResult(
        cluster_id=cluster.cluster_id, articles=tuple(contributions),
        syndicated_families=detection.families,
        syndication_algorithm_version=detection.algorithm_version,
        excluded_article_ids=detection.excluded_article_ids,
        total_contribution=total, article_contribution_score=_unit(-expm1(-total / policy.normalization_scale)),
        config_version=config.version, evaluated_at=evaluated_at,
    )

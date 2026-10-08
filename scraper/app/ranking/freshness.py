"""Decay events from meaningful reporting, with category-specific half-lives."""

from datetime import datetime, timezone
from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, field_validator

from app.ranking.article_contribution import score_article_contribution
from app.ranking.contracts import ContractModel, RankableCluster, RankingConfig


ALGORITHM_VERSION = "freshness-v1"
PositiveHours = Annotated[float, Field(gt=0.0, allow_inf_nan=False)]
_DEFAULT_CATEGORY_HALF_LIVES = {
    "politika": 24.0,
    "gospodarstvo": 36.0,
    "kriminal": 12.0,
    "sport": 6.0,
    "kultura": 72.0,
    "zdravje": 48.0,
    "okolje": 48.0,
    "lokalno": 24.0,
    "tehnologija-znanost": 72.0,
}


class FreshnessConfig(ContractModel):
    """Initial decay and novelty policy; categories don't receive importance weights."""

    default_half_life_hours: PositiveHours = 24.0
    category_half_lives_hours: dict[str, PositiveHours] = Field(
        default_factory=lambda: dict(_DEFAULT_CATEGORY_HALF_LIVES)
    )
    minimum_novelty: float = Field(default=0.5, gt=0.0, le=1.0)
    minimum_new_text_fraction: float = Field(default=0.2, gt=0.0, le=1.0)

    @field_validator("category_half_lives_hours")
    @classmethod
    def canonical_categories(cls, values: dict[str, float]) -> dict[str, float]:
        canonical = {}
        for category, hours in values.items():
            key = category.strip().casefold()
            if not key or key in canonical:
                raise ValueError("category keys must be non-empty and unique after normalization")
            canonical[key] = hours
        return {**_DEFAULT_CATEGORY_HALF_LIVES, **canonical}


class ArticleFreshnessDecision(ContractModel):
    article_id: int = Field(gt=0)
    published_at: AwareDatetime
    qualifies_as_development: bool
    reason: Literal[
        "initial_report", "meaningful_development", "syndicated_copy",
        "insufficient_content", "insufficient_comparison", "insufficient_novelty",
    ]
    novelty: float = Field(ge=0.0, le=1.0)
    new_text_fraction: float | None = Field(default=None, ge=0.0, le=1.0)


class FreshnessResult(ContractModel):
    cluster_id: int = Field(gt=0)
    category: str | None
    category_half_life_hours: PositiveHours
    used_default_half_life: bool
    freshness_score: float = Field(ge=0.0, le=1.0)
    age_hours: float | None = Field(default=None, ge=0.0)
    last_meaningful_update_at: AwareDatetime | None
    latest_meaningful_article_id: int | None = Field(default=None, gt=0)
    decay_started_at: AwareDatetime | None
    anchor_basis: Literal[
        "initial_report", "meaningful_development", "event_creation_fallback",
        "first_report_fallback", "unavailable",
    ]
    articles: tuple[ArticleFreshnessDecision, ...]
    excluded_article_ids: tuple[int, ...]
    config_version: str
    algorithm_version: str = ALGORITHM_VERSION
    article_contribution_algorithm_version: str
    syndication_algorithm_version: str
    evaluated_at: AwareDatetime


def score_freshness(
    cluster: RankableCluster,
    evaluated_at: datetime,
    config: RankingConfig,
) -> FreshnessResult:
    """Advance the event clock only for sufficient, novel, non-copied reporting.

    Publication time is the proxy for a development's time. First-seen and generic
    cluster changed_at timestamps never refresh the event. A fallback anchor is
    explicitly distinguished from a confirmed meaningful update.
    """
    policy = FreshnessConfig.model_validate(config.parameters.get("freshness", {}))
    contributions = score_article_contribution(cluster, evaluated_at, config)
    evaluated_at = contributions.evaluated_at
    articles = {article.article_id: article for article in cluster.articles}
    category = cluster.category.strip().casefold() if cluster.category else None
    category = category or None
    half_life = policy.category_half_lives_hours.get(category, policy.default_half_life_hours)
    default_half_life = category not in policy.category_half_lives_hours

    anchor = None
    basis = "unavailable"
    if contributions.articles:
        if cluster.created_at is not None and cluster.created_at <= evaluated_at:
            anchor = cluster.created_at.astimezone(timezone.utc)
            basis = "event_creation_fallback"
        # Use the earliest observation, never the latest unverified report, for
        # a fallback. Copies alone need an existing event anchor; their first
        # appearance cannot establish a newly fresh event.
        has_non_copy = any(
            articles[item.article_id].is_syndicated is not True
            and (item.syndication_family_id is None
                 or item.family_representative_article_id == item.article_id)
            for item in contributions.articles
        )
        if anchor is not None or has_non_copy:
            first_time = articles[contributions.articles[0].article_id].published_at.astimezone(timezone.utc)
            if anchor is None or first_time < anchor:
                anchor, basis = first_time, "first_report_fallback"

    latest_time = None
    latest_id = None
    decisions = []
    for item in contributions.articles:
        article = articles[item.article_id]
        published_at = article.published_at.astimezone(timezone.utc)
        is_copy = (article.is_syndicated is True or
                   (item.syndication_family_id is not None
                    and item.family_representative_article_id != item.article_id))
        qualifies = False
        if is_copy:
            reason = "syndicated_copy"
        elif item.syndication_status == "unknown":
            reason = "insufficient_content"
        elif item.compared_article_count == 0:
            # A first report establishes a new event. If creation says the event
            # existed earlier, absent comparison history cannot prove an update.
            qualifies = published_at == anchor
            reason = "initial_report" if qualifies else "insufficient_comparison"
        elif "novelty" in item.fallback_signals or item.new_text_fraction is None:
            reason = "insufficient_comparison"
        elif (item.novelty < policy.minimum_novelty
              or item.new_text_fraction < policy.minimum_new_text_fraction):
            reason = "insufficient_novelty"
        else:
            qualifies, reason = True, "meaningful_development"
        if qualifies:
            anchor = latest_time = published_at
            latest_id = article.article_id
            basis = reason
        decisions.append(ArticleFreshnessDecision(
            article_id=article.article_id, published_at=published_at,
            qualifies_as_development=qualifies, reason=reason,
            novelty=item.novelty, new_text_fraction=item.new_text_fraction,
        ))

    age_hours = (evaluated_at - anchor).total_seconds() / 3600.0 if anchor is not None else None
    freshness = 2.0 ** (-age_hours / half_life) if age_hours is not None else 0.0
    return FreshnessResult(
        cluster_id=cluster.cluster_id, category=category, category_half_life_hours=half_life,
        used_default_half_life=default_half_life, freshness_score=freshness, age_hours=age_hours,
        last_meaningful_update_at=latest_time, latest_meaningful_article_id=latest_id,
        decay_started_at=anchor, anchor_basis=basis, articles=tuple(decisions),
        excluded_article_ids=contributions.excluded_article_ids,
        config_version=config.version,
        article_contribution_algorithm_version=contributions.algorithm_version,
        syndication_algorithm_version=contributions.syndication_algorithm_version,
        evaluated_at=evaluated_at,
    )

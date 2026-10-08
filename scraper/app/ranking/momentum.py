"""Measure changes in independently written coverage across adjacent time windows."""

from collections import Counter
from datetime import datetime, timedelta, timezone
from math import expm1, fsum
from typing import Literal

from pydantic import AwareDatetime, Field

from app.ranking.article_contribution import ArticleContribution, score_article_contribution
from app.ranking.contracts import ContractModel, RankableCluster, RankingConfig


ALGORITHM_VERSION = "momentum-v1"
MomentumWindowName = Literal["history", "previous", "recent"]
MomentumReason = Literal[
    "new_independent_publisher", "meaningful_report", "syndicated_copy",
    "insufficient_content", "insufficient_new_text", "insufficient_comparison",
    "insufficient_novelty",
]


class MomentumConfig(ContractModel):
    """Initial policy for coverage rates, publisher limits, and trend sensitivity."""

    window_hours: float = Field(default=6.0, ge=1.0 / 3600.0, le=8760.0)
    new_publisher_weight: float = Field(default=0.5, ge=0.0, le=1.0)
    publisher_repeat_credit: float = Field(default=0.15, ge=0.0, lt=1.0)
    publisher_repeat_decay: float = Field(default=0.5, gt=0.0, lt=1.0)
    minimum_novelty: float = Field(default=0.5, gt=0.0, le=1.0)
    minimum_new_text_fraction: float = Field(default=0.2, gt=0.0, le=1.0)
    velocity_scale_per_hour: float = Field(default=0.5, gt=0.0)
    acceleration_weight: float = Field(default=0.4, ge=0.0, le=1.0)


class ArticleMomentumDecision(ContractModel):
    article_id: int = Field(gt=0)
    publisher_key: str
    published_at: AwareDatetime
    window: MomentumWindowName
    qualifies_as_coverage: bool
    reason: MomentumReason
    is_new_independent_publisher: bool
    novelty: float = Field(ge=0.0, le=1.0)
    new_text_fraction: float | None = Field(default=None, ge=0.0, le=1.0)
    publisher_window_ordinal: int | None = Field(default=None, gt=0)
    article_credit: float = Field(ge=0.0, le=1.0)
    new_publisher_credit: float = Field(ge=0.0, le=1.0)
    coverage_credit: float = Field(ge=0.0, le=1.0)


class MomentumWindow(ContractModel):
    """Publication interval (start, end]; history supplies context, never velocity."""

    start_at: AwareDatetime
    end_at: AwareDatetime
    article_ids: tuple[int, ...]
    independent_article_count: int = Field(ge=0)
    active_independent_publisher_count: int = Field(ge=0)
    new_independent_publishers: tuple[str, ...]
    new_independent_publisher_count: int = Field(ge=0)
    effective_article_count: float = Field(ge=0.0)
    coverage_credit: float = Field(ge=0.0)
    velocity_per_hour: float = Field(ge=0.0)


class MomentumResult(ContractModel):
    cluster_id: int = Field(gt=0)
    momentum_score: float = Field(ge=0.0, le=1.0)
    window_hours: float = Field(gt=0.0)
    previous_window: MomentumWindow
    recent_window: MomentumWindow
    velocity_change_per_hour: float
    acceleration_per_hour_squared: float
    relative_change: float = Field(ge=-1.0, le=1.0)
    trend: Literal["accelerating", "steady", "slowing", "inactive"]
    activity_score: float = Field(ge=0.0, le=1.0)
    trend_multiplier: float = Field(ge=0.0, le=1.0)
    articles: tuple[ArticleMomentumDecision, ...]
    excluded_article_ids: tuple[int, ...]
    config_version: str
    algorithm_version: str = ALGORITHM_VERSION
    article_contribution_algorithm_version: str
    syndication_algorithm_version: str
    evaluated_at: AwareDatetime


def _coverage_reason(
    item: ArticleContribution, explicitly_syndicated: bool, is_new_publisher: bool,
    policy: MomentumConfig,
) -> MomentumReason:
    if (explicitly_syndicated or
            (item.syndication_family_id is not None
             and item.family_representative_article_id != item.article_id)):
        return "syndicated_copy"
    if item.syndication_status == "unknown":
        return "insufficient_content"
    # Reject compilations of known text even if their overall body does not
    # match one syndicated family or their embeddings suggest novel reporting.
    if (item.new_text_fraction is not None
            and item.new_text_fraction < policy.minimum_new_text_fraction):
        return "insufficient_new_text"
    if is_new_publisher:
        # Independent coverage can broaden without revealing a new fact. A
        # returning publisher must meet the stronger novelty checks below.
        return "new_independent_publisher"
    if "novelty" in item.fallback_signals or item.new_text_fraction is None:
        return "insufficient_comparison"
    if item.novelty < policy.minimum_novelty:
        return "insufficient_novelty"
    return "meaningful_report"


def _summarize_window(
    decisions: list[ArticleMomentumDecision], name: MomentumWindowName,
    start: datetime, end: datetime, hours: float,
) -> MomentumWindow:
    items = [item for item in decisions if item.window == name]
    qualifying = [item for item in items if item.qualifies_as_coverage]
    new_publishers = tuple(sorted(
        item.publisher_key for item in qualifying if item.is_new_independent_publisher
    ))
    credit = fsum(item.coverage_credit for item in qualifying)
    return MomentumWindow(
        start_at=start, end_at=end, article_ids=tuple(item.article_id for item in items),
        independent_article_count=len(qualifying),
        active_independent_publisher_count=len({item.publisher_key for item in qualifying}),
        new_independent_publishers=new_publishers,
        new_independent_publisher_count=len(new_publishers),
        effective_article_count=fsum(item.article_credit for item in qualifying),
        coverage_credit=credit, velocity_per_hour=credit / hours,
    )


def score_momentum(
    cluster: RankableCluster, evaluated_at: datetime, config: RankingConfig,
) -> MomentumResult:
    """Compare coverage rates without letting copies or post volume drive momentum.

    Full eligible history identifies each publisher's first independent report.
    Only publication times in the two windows enter velocity. A returning
    publisher needs novel reporting; additional reports in a window share a
    bounded, geometrically diminishing allowance.
    """
    policy = MomentumConfig.model_validate(config.parameters.get("momentum", {}))
    contributions = score_article_contribution(cluster, evaluated_at, config)
    evaluated_at = contributions.evaluated_at
    duration = timedelta(hours=policy.window_hours)
    hours = duration.total_seconds() / 3600.0
    try:
        recent_start = evaluated_at - duration
        previous_start = recent_start - duration
    except OverflowError as error:
        raise ValueError("momentum windows exceed the supported datetime range") from error

    source_articles = {article.article_id: article for article in cluster.articles}
    independent_publishers: set[str] = set()
    window_counts: Counter[tuple[str, str]] = Counter()
    decisions = []
    for item in contributions.articles:
        article = source_articles[item.article_id]
        published_at = article.published_at.astimezone(timezone.utc)
        publisher = article.publisher_key.casefold()
        window: MomentumWindowName = (
            "recent" if published_at > recent_start else
            "previous" if published_at > previous_start else "history"
        )
        reason = _coverage_reason(
            item, article.is_syndicated is True, publisher not in independent_publishers, policy,
        )
        qualifies = reason in ("new_independent_publisher", "meaningful_report")
        is_new = reason == "new_independent_publisher"
        article_credit = publisher_credit = 0.0
        ordinal = None
        if qualifies:
            independent_publishers.add(publisher)
            if window != "history":
                key = (window, publisher)
                window_counts[key] += 1
                ordinal = window_counts[key]
                article_credit = (1.0 if ordinal == 1 else
                                  policy.publisher_repeat_credit
                                  * (1.0 - policy.publisher_repeat_decay)
                                  * policy.publisher_repeat_decay ** (ordinal - 2))
                publisher_credit = float(is_new)
        credit = (policy.new_publisher_weight * publisher_credit
                  + (1.0 - policy.new_publisher_weight) * article_credit)
        decisions.append(ArticleMomentumDecision(
            article_id=item.article_id, publisher_key=publisher, published_at=published_at,
            window=window, qualifies_as_coverage=qualifies, reason=reason,
            is_new_independent_publisher=is_new, novelty=item.novelty,
            new_text_fraction=item.new_text_fraction, publisher_window_ordinal=ordinal,
            article_credit=article_credit, new_publisher_credit=publisher_credit,
            coverage_credit=credit,
        ))

    previous = _summarize_window(decisions, "previous", previous_start, recent_start, hours)
    recent = _summarize_window(decisions, "recent", recent_start, evaluated_at, hours)
    velocity_change = recent.velocity_per_hour - previous.velocity_per_hour
    total_credit = recent.coverage_credit + previous.coverage_credit
    relative_change = ((recent.coverage_credit - previous.coverage_credit) / total_credit
                       if total_credit else 0.0)
    activity = -expm1(-recent.velocity_per_hour / policy.velocity_scale_per_hour)
    multiplier = 1.0 - policy.acceleration_weight * (1.0 - relative_change) / 2.0
    trend = ("inactive" if not total_credit else "accelerating" if velocity_change > 0.0
             else "slowing" if velocity_change < 0.0 else "steady")
    return MomentumResult(
        cluster_id=cluster.cluster_id, momentum_score=activity * multiplier, window_hours=hours,
        previous_window=previous, recent_window=recent,
        velocity_change_per_hour=velocity_change,
        acceleration_per_hour_squared=velocity_change / hours,
        relative_change=relative_change, trend=trend, activity_score=activity,
        trend_multiplier=multiplier, articles=tuple(decisions),
        excluded_article_ids=contributions.excluded_article_ids,
        config_version=config.version,
        article_contribution_algorithm_version=contributions.algorithm_version,
        syndication_algorithm_version=contributions.syndication_algorithm_version,
        evaluated_at=evaluated_at,
    )

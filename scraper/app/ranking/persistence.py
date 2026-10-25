"""Prepare database snapshots and persist scores outside the pure ranking engine."""

from collections import Counter
from datetime import datetime
import logging
from math import isfinite

from sqlalchemy import update
from sqlalchemy.orm import object_session

from database.schema import ClusterV2, Story, StoryRank

from app.ranking.article_contribution import ArticleContributionConfig
from app.ranking.cluster_confidence import ClusterConfidenceConfig
from app.ranking.contracts import RankableArticle, RankableCluster, RankingConfig
from app.ranking.coverage import CoverageConfig
from app.ranking.engine import ClusterRankingConfig, ClusterRankingExplanation, explain_cluster_ranking
from app.ranking.freshness import FreshnessConfig
from app.ranking.manual_authority import ManualAuthorityProvider
from app.ranking.momentum import MomentumConfig
from app.ranking.newsworthiness import NewsworthinessConfig
from app.ranking.publisher_authority import PublisherAuthorityConfig, with_publisher_authority
from app.ranking.syndication import SyndicationConfig, detect_syndication


DEFAULT_CONFIG_VERSION = "initial-ranking-v1"
# ranking_run.source. Cluster labels rows written against HDBSCAN snapshots.
RANKING_SOURCE_CLUSTER = "cluster"
RANKING_SOURCE_STORY = "story"
# Older observations keep score, ranked_at, rank_version, and rank_category.
# The component summary stays only on the latest row for that story.
SCORE_ONLY_COMPONENTS = {"retained": "score"}
# Cosine of normalized vectors can sit a few ulps outside [0, 1].
_SIMILARITY_EPSILON = 1e-6
CONFIG_SECTIONS = {
    "article_contribution": ArticleContributionConfig,
    "syndication": SyndicationConfig,
    "coverage": CoverageConfig,
    "publisher_authority": PublisherAuthorityConfig,
    "freshness": FreshnessConfig,
    "momentum": MomentumConfig,
    "newsworthiness": NewsworthinessConfig,
    "cluster_confidence": ClusterConfidenceConfig,
    "ranking": ClusterRankingConfig,
}


def resolve_ranking_config(config: RankingConfig) -> RankingConfig:
    """Validate settings up front and materialize defaults for reproducible storage."""
    unknown = config.parameters.keys() - CONFIG_SECTIONS.keys()
    if unknown:
        raise ValueError(f"Unknown ranking configuration sections: {sorted(unknown)}")
    return RankingConfig(version=config.version, parameters={
        name: model.model_validate(config.parameters.get(name, {})).model_dump(mode="json")
        for name, model in CONFIG_SECTIONS.items()
    })


def derive_cluster_category(
    cluster: RankableCluster, evaluated_at: datetime, config: RankingConfig,
) -> str | None:
    """One primary-category vote per publisher, excluding known family copies.

    Use each publisher's earliest categorized eligible report. Unknown-content
    reports may vote; no text match can be inferred from missing content. Ties
    are alphabetical, never based on an importance priority for a category.
    """
    detection = detect_syndication(cluster, evaluated_at, config)
    eligible = {item.article_id for item in detection.articles if (
        item.family_id is None or item.representative_article_id == item.article_id
    )}
    publishers: set[str] = set()
    votes: Counter[str] = Counter()
    for article in sorted(cluster.articles, key=lambda item: (
        item.published_at, item.first_seen_at or item.published_at, item.article_id,
    )):
        publisher = article.publisher_key.casefold()
        if article.article_id not in eligible or publisher in publishers or article.is_syndicated is True:
            continue
        category = next((value.strip().casefold() for value in article.categories if value.strip()), None)
        if category:
            publishers.add(publisher)
            votes[category] += 1
    return min(votes, key=lambda category: (-votes[category], category)) if votes else None


def membership_confidence_from_story_similarity(
    value: float | None, *, article_id: int,
) -> float | None:
    """Map centroid cosine onto the engine's membership slot, or leave it unknown.

    ``story_article.story_similarity`` is the cosine to the story centroid at
    assignment time, not an HDBSCAN probability. The engine accepts only a
    membership confidence in [0, 1] and treats None as unknown (its configured
    fallback, 0.5). An in-range cosine is that slot's closest input: cosine
    joins are at least 0.70, above the engine's weak-membership threshold of
    0.5. Missing, non-finite, and out-of-range values stay unknown so a
    negative cosine is not turned into a fake probability and does not skip
    the story. The nearest-article ``similarity`` column is a different
    measurement and is not used here.
    """
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value):
        logging.warning(
            "Article %s has story_similarity=%s; using unknown membership confidence",
            article_id, value,
        )
        return None
    if -_SIMILARITY_EPSILON <= value < 0:
        return 0.0
    if 1 < value <= 1 + _SIMILARITY_EPSILON:
        return 1.0
    if 0 <= value <= 1:
        return float(value)
    logging.warning(
        "Article %s has story_similarity=%s outside [0, 1]; using unknown membership confidence",
        article_id, value,
    )
    return None


def prepare_cluster(
    cluster: ClusterV2, evaluated_at: datetime, config: RankingConfig,
) -> RankableCluster:
    """Load all member history; snapshot creation is not an event freshness signal."""
    articles = []
    ranks = {}
    for membership in cluster.memberships:
        if membership.run_id != cluster.run_id:
            raise ValueError(f"Cluster {cluster.id} has a membership from a different run")
        article = membership.article
        llm_rank = article.llm_rank
        if llm_rank is not None and not 1 <= llm_rank <= 10:
            logging.warning("Article %s has invalid llm_rank=%s; using unknown importance", article.id, llm_rank)
            llm_rank = None
        ranks[article.news_provider_key] = article.news_provider.rank if article.news_provider else None
        articles.append(RankableArticle(
            article_id=article.id,
            publisher_key=article.news_provider_key,
            title=article.title,
            published_at=article.published_at,
            first_seen_at=article.first_seen_at,
            summary=article.summary,
            content=article.content,
            categories=tuple(article.categories or ()),
            llm_rank=llm_rank,
            embedding=tuple(article.embedding or ()),
            cluster_membership_confidence=membership.membership_confidence,
        ))
    snapshot = RankableCluster(
        cluster_id=cluster.id, articles=tuple(articles),
        # Historical cluster rows are recurring snapshots, not durable events.
        # The first member publication provides an available event anchor.
        created_at=min((article.published_at for article in articles), default=None),
    )
    snapshot = with_publisher_authority(snapshot, ManualAuthorityProvider(ranks))
    return snapshot.model_copy(update={
        "category": derive_cluster_category(snapshot, evaluated_at, config),
    })


def prepare_story(
    story: Story, evaluated_at: datetime, config: RankingConfig,
) -> RankableCluster:
    """Adapt one story to the unchanged ranking engine.

    The engine still names its input a cluster. ``cluster_id`` carries the
    story id and is not written back onto the story. ``story.created_at`` is
    not an event time; the earliest member publication is the anchor, the
    same rule the cluster loader uses for snapshot rows. Membership strength
    comes from ``story_similarity`` when it falls in [0, 1], otherwise unknown.
    """
    if story.merged_into_story_id is not None:
        raise ValueError(f"Story {story.id} is merged into {story.merged_into_story_id}")
    articles = []
    ranks = {}
    for membership in story.memberships:
        article = membership.article
        llm_rank = article.llm_rank
        if llm_rank is not None and not 1 <= llm_rank <= 10:
            logging.warning(
                "Article %s has invalid llm_rank=%s; using unknown importance",
                article.id, llm_rank,
            )
            llm_rank = None
        provider = article.news_provider
        ranks[article.news_provider_key] = provider.rank if provider else None
        articles.append(RankableArticle(
            article_id=article.id,
            publisher_key=article.news_provider_key,
            title=article.title,
            published_at=article.published_at,
            first_seen_at=article.first_seen_at,
            summary=article.summary,
            content=article.content,
            categories=tuple(article.categories or ()),
            llm_rank=llm_rank,
            embedding=tuple(article.embedding or ()),
            cluster_membership_confidence=membership_confidence_from_story_similarity(
                membership.story_similarity, article_id=article.id,
            ),
        ))
    snapshot = RankableCluster(
        cluster_id=story.id, articles=tuple(articles),
        created_at=min((article.published_at for article in articles), default=None),
    )
    snapshot = with_publisher_authority(snapshot, ManualAuthorityProvider(ranks))
    return snapshot.model_copy(update={
        "category": derive_cluster_category(snapshot, evaluated_at, config),
    })


def _summary_components(explanation: ClusterRankingExplanation) -> dict:
    """Small, stable fields for cluster_v2.rank_components.

    The full ClusterRankingExplanation is returned to the caller and is not
    stored. Dry-run uses that return value; production rows keep this summary.
    """
    return {
        **explanation.result.components.model_dump(mode="json"),
        "base_score": explanation.base_score,
        "freshness_factor": explanation.freshness_factor,
        "confidence_factor": explanation.confidence_factor,
        "terms": [term.model_dump(mode="json") for term in explanation.terms],
        "last_meaningful_update_at": (
            explanation.freshness.last_meaningful_update_at.isoformat()
            if explanation.freshness.last_meaningful_update_at else None
        ),
        "decay_started_at": (
            explanation.freshness.decay_started_at.isoformat()
            if explanation.freshness.decay_started_at else None
        ),
        "freshness_anchor_basis": explanation.freshness.anchor_basis,
        "category_half_life_hours": explanation.freshness.category_half_life_hours,
        "algorithm_versions": {
            name: getattr(explanation, name).algorithm_version for name in (
                "article_contribution", "coverage", "publisher_authority", "momentum",
                "newsworthiness", "freshness", "confidence",
            )
        },
        "syndication_algorithm_version": explanation.coverage.syndication_algorithm_version,
        "category_policy": "earliest-report-per-publisher-excluding-family-copies-v1",
    }


def rank_and_save_cluster(
    cluster: ClusterV2, evaluated_at: datetime, config: RankingConfig, *, dry_run: bool = False,
    ranking_run_id: int | None = None,
) -> ClusterRankingExplanation:
    """Update the tracked cluster; the caller owns its transaction and commit.

    Always returns the full explanation. ``dry_run=True`` writes nothing, which
    is how callers inspect that explanation. A real save stores summary
    component fields only. Configuration is stored once on ``ranking_run``.
    """
    config = resolve_ranking_config(config)
    snapshot = prepare_cluster(cluster, evaluated_at, config)
    explanation = explain_cluster_ranking(snapshot, evaluated_at, config)
    if dry_run:
        return explanation
    cluster.rank_score = explanation.result.score
    cluster.ranking_run_id = ranking_run_id
    cluster.ranked_at = explanation.result.evaluated_at
    cluster.rank_version = explanation.algorithm_version
    cluster.rank_category = snapshot.category
    # Summary only. The full explanation stays on the returned object so a
    # dry-run can inspect it; it is not written on every cluster row.
    # rank_config lives once on ranking_run, referenced by ranking_run_id.
    cluster.rank_components = _summary_components(explanation)
    return explanation


def rank_and_save_story(
    story: Story, evaluated_at: datetime, config: RankingConfig, *, dry_run: bool = False,
    ranking_run_id: int | None = None,
) -> ClusterRankingExplanation:
    """Insert one story_rank row. The story and its articles are not modified.

    ``dry_run=True`` returns the explanation and writes nothing. A real save
    requires ``ranking_run_id`` and adds a ``StoryRank`` to the story's
    session; the caller owns the transaction. The new row keeps the component
    summary. Earlier rows for the same story are reduced to
    ``SCORE_ONLY_COMPONENTS`` in that same session, so a rollback drops the
    insert and the slim together. Score, time, version, and category on those
    earlier rows stay. Configuration stays on ``ranking_run``. This does not
    read or write cluster tables, and it does not delete rows.
    """
    config = resolve_ranking_config(config)
    snapshot = prepare_story(story, evaluated_at, config)
    explanation = explain_cluster_ranking(snapshot, evaluated_at, config)
    if dry_run:
        return explanation
    if ranking_run_id is None:
        raise ValueError("ranking_run_id is required to record a story score")
    session = object_session(story)
    if session is None:
        raise RuntimeError(f"Story {story.id} is not attached to a session")
    # Reduce rows that still hold a full summary. After the first slim only
    # the previous latest row matches, via ix_story_rank_story_id.
    session.execute(
        update(StoryRank)
        .where(
            StoryRank.story_id == story.id,
            StoryRank.ranking_run_id != ranking_run_id,
            StoryRank.rank_components.is_distinct_from(SCORE_ONLY_COMPONENTS),
        )
        .values(rank_components=SCORE_ONLY_COMPONENTS)
    )
    session.add(StoryRank(
        ranking_run_id=ranking_run_id,
        story_id=story.id,
        score=explanation.result.score,
        ranked_at=explanation.result.evaluated_at,
        rank_version=explanation.algorithm_version,
        rank_components=_summary_components(explanation),
        rank_category=snapshot.category,
    ))
    return explanation


def expire_cluster_ranking(
    cluster: ClusterV2, evaluated_at: datetime, *, cutoff: datetime,
    config: RankingConfig, ranking_run_id: int,
) -> None:
    """Record a policy zero, replacing any stale calculation and its explanation."""
    cluster.rank_score = 0.0
    cluster.ranked_at = evaluated_at
    cluster.ranking_run_id = ranking_run_id
    cluster.rank_version = "expired-v1"
    cluster.rank_category = None
    cluster.rank_components = {
        "status": "expired",
        "reason": "not_in_scored_cluster_run",
        "config_version": config.version,
        "score": 0.0,
        "cutoff": cutoff.isoformat(),
        "snapshot_created_at": cluster.created_at.isoformat(),
        "evaluated_at": evaluated_at.isoformat(),
    }

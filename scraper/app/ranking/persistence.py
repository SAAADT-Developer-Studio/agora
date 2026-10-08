"""Prepare database snapshots and persist scores outside the pure ranking engine."""

from collections import Counter
from datetime import datetime
import logging

from database.schema import ClusterV2

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


def rank_and_save_cluster(
    cluster: ClusterV2, evaluated_at: datetime, config: RankingConfig, *, dry_run: bool = False,
    ranking_run_id: int | None = None,
) -> ClusterRankingExplanation:
    """Update the tracked cluster; the caller owns its transaction and commit."""
    config = resolve_ranking_config(config)
    snapshot = prepare_cluster(cluster, evaluated_at, config)
    explanation = explain_cluster_ranking(snapshot, evaluated_at, config)
    if dry_run:
        return explanation
    cluster.rank_score = explanation.result.score
    cluster.ranking_run_id = ranking_run_id
    cluster.ranked_at = explanation.result.evaluated_at
    cluster.rank_version = explanation.algorithm_version
    cluster.rank_config = config.model_dump(mode="json")
    cluster.rank_category = snapshot.category
    cluster.rank_components = {
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
        # Keep the summary keys above compatible with existing readers, and retain
        # every component's article/publisher decisions for later inspection.
        "explanation": explanation.model_dump(mode="json"),
    }
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
    cluster.rank_config = config.model_dump(mode="json")
    cluster.rank_category = None
    cluster.rank_components = {
        "status": "expired",
        "reason": "snapshot_outside_ranking_window",
        "score": 0.0,
        "cutoff": cutoff.isoformat(),
        "snapshot_created_at": cluster.created_at.isoformat(),
        "evaluated_at": evaluated_at.isoformat(),
    }

"""
Repository pattern implementation for database operations.
Separates concerns and provides clean abstractions for each entity.
"""

from abc import ABC, abstractmethod  # in case we want to define the repository interface later
from sqlalchemy import exists, func, or_, select
from sqlalchemy.orm import Session, selectinload, load_only
from .schema import (
    Article,
    NewsProvider,
    Cluster,
    ClusterRun,
    ArticleCluster,
    ClusterV2,
    Story,
    StoryArticle,
)
from datetime import datetime, timedelta
from typing import Sequence


class ArticleRepository:
    """Repository for Article entity operations."""

    def __init__(self, session: Session):
        self.session = session

    def get_by_urls(self, urls: list[str]) -> set[str]:
        """Get URLs that already exist in the database."""
        query_results = self.session.query(Article.url).filter(Article.url.in_(urls)).all()
        return {result[0] for result in query_results}

    def bulk_create(self, articles: list[Article]) -> None:
        """Bulk insert articles."""
        self.session.add_all(articles)

    def get_clustered_and_pad_articles(self) -> Sequence[Article]:
        clustered = select(Article).where(Article.cluster_id.is_not(None)).cte(name="clustered")

        clustered_cnt_sq = select(func.count()).select_from(clustered).scalar_subquery()

        pad = (
            select(Article)
            .where(Article.cluster_id.is_(None))
            .order_by(Article.published_at.desc())
            .limit(func.greatest(0, 2000 - clustered_cnt_sq))
            .cte(name="pad")
        )

        query = select(clustered).union_all(select(pad))
        stmt = select(Article).from_statement(query)
        result = self.session.scalars(stmt).all()
        return result

    def get_latest(
        self, count: int | None, *, since: datetime | None = None, through: datetime | None = None,
    ) -> Sequence[Article]:
        query = select(Article).order_by(Article.published_at.desc()).limit(count)
        if since is not None:
            query = query.where(Article.published_at >= since)
        if through is not None:
            query = query.where(Article.published_at <= through)
        return self.session.scalars(query).all()

    def get_all_since(self, from_date: datetime) -> Sequence[Article]:
        # limit to 3000 just in case
        return self.session.scalars(
            select(Article)
            .where(Article.published_at > from_date)
            .order_by(Article.published_at.desc())
            .options(load_only(Article.id, Article.title, Article.embedding, Article.published_at))
            .limit(3000)
        ).all()


class NewsProviderRepository:
    """Repository for NewsProvider entity operations."""

    def __init__(self, session: Session):
        self.session = session

    def get_existing_keys(self) -> set[str]:
        """Get all existing provider keys."""
        return {key for (key,) in self.session.query(NewsProvider.key).all()}

    def get_by_key(self, key: str) -> NewsProvider | None:
        """Get news provider by key."""
        return self.session.query(NewsProvider).filter(NewsProvider.key == key).first()

    def get_by_keys(self, keys: list[str]) -> list[NewsProvider]:
        """Get news providers by keys."""
        return self.session.query(NewsProvider).filter(NewsProvider.key.in_(keys)).all()

    def bulk_create(self, providers: list[NewsProvider]) -> None:
        """Bulk insert news providers."""
        self.session.bulk_save_objects(providers)  # TODO: use add_all for consistency

    def create(self, provider: NewsProvider) -> NewsProvider:
        """Create a single news provider."""
        self.session.add(provider)
        return provider

    def update(self, provider: NewsProvider) -> NewsProvider:
        """Update a news provider (already tracked by session)."""
        return provider


class ClusterRepository:
    """Repository for Cluster entity operations."""

    def __init__(self, session: Session):
        self.session = session

    def get_all_nonempty(self) -> Sequence[Cluster]:
        """Get all clusters that have at least one article."""
        # i don't think this works fully?
        stmt = select(Cluster).join(Article, Cluster.id == Article.cluster_id).group_by(Cluster.id)
        return self.session.scalars(stmt).all()


class ClusterV2Repository:
    """Repository for ClusterV2 entity operations."""

    def __init__(self, session: Session):
        self.session = session

    def bulk_create(self, clusters: list[ClusterV2]) -> None:
        """Bulk insert clusters."""
        self.session.add_all(clusters)

    def get_ranking_batch(
        self, *, since: datetime, through: datetime, after_id: int = 0, limit: int = 100,
    ) -> Sequence[ClusterV2]:
        """Page through recent snapshots, retaining their complete article history."""
        if limit < 1:
            raise ValueError("limit must be positive")
        return self.session.scalars(
            select(ClusterV2)
            .where(
                ClusterV2.created_at >= since,
                ClusterV2.created_at <= through,
                ClusterV2.id > after_id,
            )
            .order_by(ClusterV2.id)
            .limit(limit)
            .options(
                # Previous explanations can be large; scoring replaces them.
                load_only(ClusterV2.id, ClusterV2.run_id, ClusterV2.created_at),
                selectinload(ClusterV2.memberships)
                .selectinload(ArticleCluster.article)
                .load_only(
                    Article.id, Article.title, Article.published_at, Article.first_seen_at,
                    Article.summary, Article.content, Article.categories, Article.llm_rank,
                    Article.embedding, Article.news_provider_key,
                )
                .selectinload(Article.news_provider)
                .load_only(NewsProvider.key, NewsProvider.rank)
            )
        ).all()


    def get_expired_ranking_batch(
        self, *, before: datetime, after_id: int = 0, limit: int = 100,
    ) -> Sequence[ClusterV2]:
        """Expire old snapshots once, without loading their articles or explanations."""
        if limit < 1:
            raise ValueError("limit must be positive")
        return self.session.scalars(
            select(ClusterV2)
            .where(
                ClusterV2.created_at < before,
                ClusterV2.id > after_id,
                or_(
                    ClusterV2.rank_score.is_distinct_from(0),
                    ClusterV2.rank_components["status"].astext.is_distinct_from("expired"),
                ),
            )
            .order_by(ClusterV2.id)
            .limit(limit)
            .options(load_only(ClusterV2.id, ClusterV2.created_at))
        ).all()


class ClusterRunRepository:
    """Repository for ClusterRun entity operations."""

    def __init__(self, session: Session):
        self.session = session

    def create(self, cluster_run: ClusterRun) -> None:
        """Create a new cluster run."""
        self.session.add(cluster_run)

    def get_latest(self) -> ClusterRun | None:
        """Get the latest cluster run."""
        return self.session.scalars(
            select(ClusterRun)
            .options(
                selectinload(ClusterRun.clusters)
                .selectinload(ClusterV2.memberships)
                .selectinload(ArticleCluster.article)
                .load_only(Article.id, Article.title, Article.embedding, Article.published_at)
            )
            .order_by(ClusterRun.created_at.desc())
            .limit(1)
        ).first()


class StoryRepository:
    def __init__(self, session: Session):
        self.session = session

    def get_assigned_since(self, since: datetime) -> Sequence[tuple[int, int, list[float]]]:
        stmt = (
            select(Article.id, StoryArticle.story_id, Article.embedding)
            .join(StoryArticle, StoryArticle.article_id == Article.id)
            .where(Article.published_at > since)
        )
        return self.session.execute(stmt).tuples().all()

    def get_unassigned_since(self, since: datetime, limit: int = 3000) -> Sequence[Article]:
        return self.session.scalars(
            select(Article)
            .where(Article.published_at > since)
            .where(~exists(select(StoryArticle.id).where(StoryArticle.article_id == Article.id)))
            .order_by(Article.published_at.asc())
            .options(load_only(Article.id, Article.title, Article.embedding, Article.published_at))
            .limit(limit)
        ).all()

    def get_by_ids(self, story_ids: list[int]) -> dict[int, Story]:
        if not story_ids:
            return {}
        stories = self.session.scalars(select(Story).where(Story.id.in_(story_ids))).all()
        return {story.id: story for story in stories}

    def create(self, story: Story) -> None:
        self.session.add(story)

    def add_membership(self, membership: StoryArticle) -> None:
        self.session.add(membership)

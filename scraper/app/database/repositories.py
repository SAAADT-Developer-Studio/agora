"""
Repository pattern implementation for database operations.
Separates concerns and provides clean abstractions for each entity.
"""

from abc import ABC, abstractmethod  # in case we want to define the repository interface later
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from .schema import Article, NewsProvider, Cluster
from datetime import datetime, timedelta, timezone


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

    def get_clustered_and_pad_articles(self) -> list[Article]:
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

    def get_by_id(self, cluster_id: int) -> Cluster | None:
        """Get cluster by ID."""
        return self.session.query(Cluster).filter(Cluster.id == cluster_id).first()

    def bulk_create(self, clusters: list[Cluster]) -> None:
        """Bulk insert clusters."""
        self.session.add_all(clusters)

    def delete_by_ids(self, cluster_ids: list[int]) -> None:
        """Delete clusters by IDs."""
        self.session.query(Cluster).filter(Cluster.id.in_(cluster_ids)).delete(
            synchronize_session=False
        )

    def delete_old_clusters(self) -> None:
        """Delete clusters whose most recent article is older than 3 days."""
        three_days_ago = datetime.now() - timedelta(days=3)

        subq = (
            self.session.query(Article.cluster_id)
            .group_by(Article.cluster_id)
            .having(func.max(Article.published_at) < three_days_ago)
            .subquery()
        )
        self.session.query(Cluster).filter(
            Cluster.id.in_(select(subq.c.cluster_id)), Cluster.id.isnot(None)
        ).delete(synchronize_session=False)

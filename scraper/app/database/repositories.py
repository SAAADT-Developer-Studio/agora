"""
Repository pattern implementation for database operations.
Separates concerns and provides clean abstractions for each entity.
"""

from abc import ABC, abstractmethod  # in case we want to define the repository interface later
from sqlalchemy.orm import Session
from .database import Article, NewsProvider


class ArticleRepository:
    """Repository for Article entity operations."""

    def __init__(self, session: Session):
        self.session = session

    def get_existing_urls(self, urls: list[str]) -> set[str]:
        """Get URLs that already exist in the database."""
        query_results = self.session.query(Article.url).filter(Article.url.in_(urls)).all()
        return {result[0] for result in query_results}

    def get_articles_with_summaries(self) -> list[Article]:
        """Get all articles that have summaries."""
        return self.session.query(Article).filter(Article.summary.isnot(None)).all()

    def get_by_id(self, article_id: int) -> Article | None:
        """Get article by ID."""
        return self.session.query(Article).filter(Article.id == article_id).first()

    def get_by_url(self, url: str) -> Article | None:
        """Get article by URL."""
        return self.session.query(Article).filter(Article.url == url).first()

    def bulk_create(self, articles: list[Article]) -> None:
        """Bulk insert articles."""
        self.session.bulk_save_objects(articles)

    def create(self, article: Article) -> Article:
        """Create a single article."""
        self.session.add(article)
        return article


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
        self.session.bulk_save_objects(providers)

    def create(self, provider: NewsProvider) -> NewsProvider:
        """Create a single news provider."""
        self.session.add(provider)
        return provider

    def update(self, provider: NewsProvider) -> NewsProvider:
        """Update a news provider (already tracked by session)."""
        return provider

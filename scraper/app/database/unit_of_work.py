"""
Unit of Work pattern for managing database transactions.
Provides consistent transaction boundaries and resource management.
"""

from contextlib import contextmanager
from typing import Generator
from sqlalchemy.orm import Session
from .database import Session as SessionMaker
from .repositories import ArticleRepository, NewsProviderRepository


class UnitOfWork:
    """
    Unit of Work pattern implementation.
    Manages database sessions and provides repository access.
    """

    def __init__(self, session: Session | None = None):
        self._session = session
        self._articles: ArticleRepository | None = None
        self._news_providers: NewsProviderRepository | None = None

    @property
    def articles(self) -> ArticleRepository:
        """Get the article repository."""
        if self._articles is None:
            self._articles = ArticleRepository(self.session)
        return self._articles

    @property
    def news_providers(self) -> NewsProviderRepository:
        """Get the news provider repository."""
        if self._news_providers is None:
            self._news_providers = NewsProviderRepository(self.session)
        return self._news_providers

    @property
    def session(self) -> Session:
        """Get the current session."""
        if self._session is None:
            self._session = SessionMaker()
        return self._session

    def commit(self) -> None:
        """Commit the current transaction."""
        self.session.commit()

    def rollback(self) -> None:
        """Rollback the current transaction."""
        self.session.rollback()

    def close(self) -> None:
        """Close the session."""
        if self._session:
            self._session.close()
            self._session = None
            self._articles = None
            self._news_providers = None


@contextmanager
def database_session() -> Generator[UnitOfWork, None, None]:
    """
    Context manager for database operations.
    Automatically handles commit/rollback and cleanup.

    Usage:
        with database_session() as uow:
            articles = uow.articles.get_existing_urls(urls)
            uow.articles.bulk_create(new_articles)
            # Transaction automatically committed on success
    """
    uow = UnitOfWork()
    try:
        yield uow
        uow.commit()
    except Exception:
        uow.rollback()
        raise
    finally:
        uow.close()


@contextmanager
def database_transaction(uow: UnitOfWork) -> Generator[UnitOfWork, None, None]:
    """
    Context manager for nested transactions within an existing UnitOfWork.

    Usage:
        uow = UnitOfWork()
        try:
            with database_transaction(uow):
                # Some operations
                pass
            with database_transaction(uow):
                # More operations
                pass
            uow.commit()  # Commit everything
        finally:
            uow.close()
    """
    try:
        yield uow
    except Exception:
        uow.rollback()
        raise

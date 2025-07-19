"""
Database package with clean abstractions.

This package provides:
- Repository pattern for data access
- Unit of Work pattern for transaction management
- Service layer for business logic
"""

from .database import Article, NewsProvider, Base, engine, Session
from .repositories import ArticleRepository, NewsProviderRepository
from .unit_of_work import UnitOfWork, database_session, database_transaction
from .services import ArticleService, NewsProviderService

__all__ = [
    # Models
    "Article",
    "NewsProvider",
    "Base",
    "engine",
    "Session",
    # Repositories
    "ArticleRepository",
    "NewsProviderRepository",
    # Unit of Work
    "UnitOfWork",
    "database_session",
    "database_transaction",
    # Services
    "ArticleService",
    "NewsProviderService",
]

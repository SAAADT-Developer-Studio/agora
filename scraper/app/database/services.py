"""
Service layer for business logic.
Contains application-specific operations that combine repository methods.
"""

import app.providers.news_provider as news_provider_module
from .unit_of_work import UnitOfWork, database_session
from .schema import Article, NewsProvider
from app.providers.ranks import assign_ranks


class ArticleService:
    """Service for article-related business operations."""

    @staticmethod
    def filter_new_articles(article_urls: list[str], uow: UnitOfWork) -> set[str]:
        """Get URLs of articles that don't exist in the database."""
        existing_urls = uow.articles.get_existing_urls(article_urls)
        return set(article_urls) - existing_urls

    @staticmethod
    def bulk_create_articles(articles: list[Article], uow: UnitOfWork) -> None:
        """Bulk create articles with proper error handling."""
        if not articles:
            return
        uow.articles.bulk_create(articles)


class NewsProviderService:
    """Service for news provider-related business operations."""

    @staticmethod
    def sync_providers(providers: list[news_provider_module.NewsProvider]) -> None:
        """
        Synchronize news providers with the database.
        Updates existing providers and creates new ones.
        """
        assign_ranks(providers)
        with database_session() as uow:
            existing_keys = uow.news_providers.get_existing_keys()

            # Separate into new and existing
            new_providers_data = [p for p in providers if p.key not in existing_keys]
            existing_providers_data = [p for p in providers if p.key in existing_keys]

            # Create new providers
            new_providers = [
                NewsProvider(
                    name=p.name, key=p.key, url=p.url, rank=p.rank, bias_rating=p.bias_rating
                )
                for p in new_providers_data
            ]
            if new_providers:
                uow.news_providers.bulk_create(new_providers)

            # Update existing providers
            if existing_providers_data:
                existing_keys_to_update = [p.key for p in existing_providers_data]
                existing_providers = uow.news_providers.get_by_keys(existing_keys_to_update)

                # Create lookup map
                provider_data_map = {p.key: p for p in existing_providers_data}

                # Update attributes
                for provider in existing_providers:
                    if provider_data := provider_data_map.get(provider.key):
                        provider.name = provider_data.name
                        provider.url = provider_data.url
                        provider.rank = provider_data.rank
                        provider.bias_rating = provider_data.bias_rating

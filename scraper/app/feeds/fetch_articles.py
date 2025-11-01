import asyncio
import logging
from datetime import datetime, timedelta
from typing import Callable
from tenacity import retry, stop_after_attempt, wait_exponential
from app import config
from app.providers.providers import PROVIDERS
from app.providers.news_provider import NewsProvider, ArticleMetadata
from app.providers.enums import ProviderKey


CONCURRENCY_LIMIT = 5
RETRY_ATTEMPTS = 2

semaphore = asyncio.Semaphore(CONCURRENCY_LIMIT)


def is_recent(date: datetime) -> bool:
    return date > datetime.now(date.tzinfo) - timedelta(**config.TIME_WINDOW)


EXCLUSION_RULES: list[tuple[str, Callable[[ArticleMetadata], bool]]] = [
    (
        ProviderKey.STA.value,
        lambda a: a.title.startswith(("Razmere na slovenskih cestah ob", "Pregled - ")),
    ),
]


def filter_out_useless_articles(articles: list[ArticleMetadata]) -> list[ArticleMetadata]:
    return [
        article
        for article in articles
        if not any(
            article.provider_key == provider_key and should_exclude(article)
            for provider_key, should_exclude in EXCLUSION_RULES
        )
    ]


@retry(
    stop=stop_after_attempt(RETRY_ATTEMPTS),
    wait=wait_exponential(multiplier=1, min=1, max=10),
)
async def fetch(provider: NewsProvider):
    async with semaphore:
        logging.info(f"Fetching articles from {provider.key}...")
        articles = await provider.fetch_articles()
        return [article for article in articles if is_recent(article.published_at)]


async def fetch_articles(provider_keys: list[str] | None = None):
    providers_map = {provider.key: provider for provider in PROVIDERS}

    if not provider_keys:
        provider_keys = list(providers_map.keys())

    tasks = [fetch(providers_map[key]) for key in provider_keys]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    successes: list[ArticleMetadata] = []

    for provider_key, result in zip(provider_keys, results):
        if isinstance(result, Exception):
            logging.error(f"Failed to fetch from {provider_key}: {result}")
        elif isinstance(result, list):
            successes.extend(result)
            logging.info(f"Fetched {len(result)} articles from {provider_key}")

    return filter_out_useless_articles(successes)

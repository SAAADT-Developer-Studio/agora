from app.providers.news_provider import NewsProvider, ArticleMetadata
from app.providers.providers import ProviderKey


class ReporterProvider(NewsProvider):
    def __init__(self):
        super().__init__(
            key=ProviderKey.REPORTER.value,
            name="Reporter",
            url="https://reporter.si",
            rss_feeds=["https://reporter.si/rss/site.xml"],
        )

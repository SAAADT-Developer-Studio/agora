from app.providers.news_provider import NewsProvider, ArticleMetadata
from app.providers.providers import ProviderKey


class Svet24Provider(NewsProvider):
    def __init__(self):
        super().__init__(
            key=ProviderKey.SVET24.value,
            name="Svet24",
            url="https://www.svet24.si",
            rss_feeds=["https://svet24.si/rss/site.xml"],
        )

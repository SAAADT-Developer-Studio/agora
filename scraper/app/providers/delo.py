from app.providers.news_provider import NewsProvider
from app.providers.providers import ProviderKey


class DeloProvider(NewsProvider):
    def __init__(self):
        super().__init__(
            key=ProviderKey.DELO.value,
            name="Delo",
            url="https://www.delo.si",
            rss_feeds=["https://www.delo.si/rss"],
        )

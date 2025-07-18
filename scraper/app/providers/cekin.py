from app.providers.news_provider import NewsProvider
from app.providers.providers import ProviderKey


class CekinProvider(NewsProvider):
    def __init__(self):
        super().__init__(
            key=ProviderKey.CEKIN.value,
            name="Cekin",
            url="https://cekin.si",
            rss_feeds=["https://cekin.si/rss"],
        )

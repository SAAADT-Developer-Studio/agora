from app.providers.news_provider import NewsProvider
from app.providers.providers import ProviderKey


class DnevnikProvider(NewsProvider):
    def __init__(self):
        super().__init__(
            key=ProviderKey.DNEVNIK.value,
            name="Dnevnik",
            url="https://www.dnevnik.si",
            rss_feeds=["https://www.dnevnik.si/rss.xml"],
        )

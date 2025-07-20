from app.providers.news_provider import NewsProvider, ArticleMetadata
from app.providers.keys import ProviderKey


class Zurnal24Provider(NewsProvider):
    def __init__(self):
        super().__init__(
            key=ProviderKey.ZURNAL24.value,
            name="Žurnal24",
            url="https://www.zurnal24.si",
            rss_feeds=["https://www.zurnal24.si/feeds/latest"],
        )

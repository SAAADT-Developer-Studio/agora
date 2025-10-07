from app.providers.news_provider import NewsProvider
from app.providers.enums import ProviderKey, BiasRating


class DeloProvider(NewsProvider):
    def __init__(self):
        super().__init__(
            key=ProviderKey.DELO.value,
            name="Delo",
            url="https://www.delo.si",
            rss_feeds=["https://www.delo.si/rss"],
            bias_rating=BiasRating.LEFT.value,
        )

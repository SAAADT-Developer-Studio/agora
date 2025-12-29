from app.providers.news_provider import NewsProvider
from app.providers.enums import ProviderKey, BiasRating


class CekinProvider(NewsProvider):
    def __init__(self):
        super().__init__(
            key=ProviderKey.CEKIN.value,
            name="Cekin",
            url="https://cekin.si",
            rss_feeds=["https://cekin.si/rss"],
            bias_rating=BiasRating.CENTER_LEFT.value,
        )

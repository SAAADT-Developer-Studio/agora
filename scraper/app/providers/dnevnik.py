from app.providers.news_provider import NewsProvider
from app.providers.enums import ProviderKey, BiasRating


class DnevnikProvider(NewsProvider):
    def __init__(self):
        super().__init__(
            key=ProviderKey.DNEVNIK.value,
            name="Dnevnik",
            url="https://www.dnevnik.si",
            rss_feeds=["https://www.dnevnik.si/rss.xml"],
            bias_rating=BiasRating.LEFT.value,
        )

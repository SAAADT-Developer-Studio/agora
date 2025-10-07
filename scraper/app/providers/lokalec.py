from app.providers.news_provider import NewsProvider
from app.providers.enums import ProviderKey, BiasRating


class LokalecProvider(NewsProvider):
    def __init__(self):
        super().__init__(
            key=ProviderKey.LOKALEC.value,
            name="Lokalec",
            url="https://www.lokalec.si",
            rss_feeds=["https://www.lokalec.si/feed/"],
            bias_rating=BiasRating.CENTER.value,
        )

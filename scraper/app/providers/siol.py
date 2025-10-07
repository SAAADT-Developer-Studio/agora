from app.providers.news_provider import NewsProvider, ArticleMetadata
from app.providers.enums import ProviderKey, BiasRating


class SiolProvider(NewsProvider):
    def __init__(self):
        super().__init__(
            key=ProviderKey.SIOL.value,
            name="Siol",
            url="https://siol.net",
            rss_feeds=["https://siol.net/feeds/latest"],
            bias_rating=BiasRating.CENTER.value,
        )

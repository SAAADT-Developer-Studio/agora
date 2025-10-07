from app.providers.news_provider import NewsProvider, ArticleMetadata
from app.providers.enums import ProviderKey, BiasRating


class SlovenskeNoviceProvider(NewsProvider):
    def __init__(self):
        super().__init__(
            key=ProviderKey.SLOVENSKENOVICE.value,
            name="Slovenske Novice",
            url="https://www.slovenskenovice.si",
            rss_feeds=["https://www.slovenskenovice.si/rss"],
            bias_rating=BiasRating.CENTER_LEFT.value,
        )

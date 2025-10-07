from app.providers.news_provider import NewsProvider
from app.providers.enums import ProviderKey, BiasRating


class NecenzuriranoProvider(NewsProvider):
    def __init__(self):
        super().__init__(
            key=ProviderKey.NECENZURIRANO.value,
            name="Necenzurirano",
            url="https://necenzurirano.si",
            rss_feeds=["https://necenzurirano.si/rss/site.xml"],
            bias_rating=BiasRating.LEFT.value,
        )

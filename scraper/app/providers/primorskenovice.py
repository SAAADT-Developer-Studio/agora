import httpx
import feedparser
from app.providers.news_provider import NewsProvider, ArticleMetadata
from app.providers.enums import ProviderKey, BiasRating


class PrimorskeNoviceProvider(NewsProvider):
    def __init__(self):
        super().__init__(
            key=ProviderKey.PRIMORSKENOVICE.value,
            name="Primorske Novice",
            url="https://primorske.svet24.si",
            rss_feeds=["https://primorske.svet24.si/rss.xml"],
            bias_rating=BiasRating.CENTER_LEFT.value,
        )
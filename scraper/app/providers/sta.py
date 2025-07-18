from app.providers.news_provider import NewsProvider, ArticleMetadata
from app.providers.providers import ProviderKey


class STAProvider(NewsProvider):
    def __init__(self):
        super().__init__(
            key=ProviderKey.STA.value,
            name="Slovenska tiskovna agencija",
            url="https://www.sta.si",
            rss_feeds=["https://www.sta.si/rss-0"],
        )

from app.providers.news_provider import NewsProvider
from app.providers.providers import ProviderKey


class RTVProvider(NewsProvider):
    def __init__(self):
        super().__init__(
            key=ProviderKey.RTV.value,
            name="RTV",
            url="https://www.rtvslo.si",
            rss_feeds=["https://img.rtvslo.si/feeds/00.xml"],
        )

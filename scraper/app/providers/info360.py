from app.providers.news_provider import NewsProvider
from app.providers.keys import ProviderKey


class Info360Provider(NewsProvider):
    def __init__(self):
        super().__init__(
            key=ProviderKey.INFO360.value,
            name="Info360",
            url="https://info360.si/",
            rss_feeds=["https://info360.si/rss.xml"],
        )

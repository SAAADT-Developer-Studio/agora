from app.providers.news_provider import NewsProvider
from app.providers.enums import ProviderKey


class LjNoviceProvider(NewsProvider):
    def __init__(self):
        super().__init__(
            key=ProviderKey.LJUBLJANSKENOVICE.value,
            name="Ljubljanske novice",
            url="https://ljnovice.si/",
            rss_feeds=["https://ljnovice.si/feed/"],
        )

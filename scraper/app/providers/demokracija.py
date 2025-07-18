from app.providers.news_provider import NewsProvider
from app.providers.providers import ProviderKey


class DemokracijaProvider(NewsProvider):
    def __init__(self):
        super().__init__(
            key=ProviderKey.DEMOKRACIJA.value,
            name="Demokracija",
            url="https://demokracija.si/",
            rss_feeds=["https://demokracija.si/feed/"],
        )

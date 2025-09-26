from app.providers.news_provider import NewsProvider
from app.providers.keys import ProviderKey


class PrimorskeNoviceProvider(NewsProvider):
    def __init__(self):
        super().__init__(
            key=ProviderKey.PRIMORSKENOVICE.value,
            name="Primorske Novice",
            url="https://primorske.svet24.si",
            rss_feeds=["https://www.planet-tv.si/rss"],
        )

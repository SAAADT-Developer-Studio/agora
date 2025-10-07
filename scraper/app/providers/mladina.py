from app.providers.news_provider import NewsProvider
from app.providers.enums import ProviderKey, BiasRating


class MladinaProvider(NewsProvider):
    def __init__(self):
        super().__init__(
            key=ProviderKey.MLADINA.value,
            name="Mladina",
            url="https://www.mladina.si",
            rss_feeds=["https://feeds.feedburner.com/Mladina"],
            # Thu, 3 Jul 2025 22:00:00 GMT
            rss_date_format="%a, %d %b %Y %H:%M:%S %Z",
            bias_rating=BiasRating.LEFT.value,
        )

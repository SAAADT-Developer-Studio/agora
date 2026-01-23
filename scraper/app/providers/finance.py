from app.providers.news_provider import NewsProvider
from app.providers.enums import ProviderKey, BiasRating


class FinanceProvider(NewsProvider):
    def __init__(self):
        super().__init__(
            key=ProviderKey.FINANCE.value,
            name="Finance.si",
            url="https://www.finance.si",
            rss_feeds=["https://feeds.feedburner.com/financesi"],
            bias_rating=BiasRating.CENTER_RIGHT.value,
        )

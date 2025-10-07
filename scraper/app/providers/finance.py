from app.providers.news_provider import NewsProvider
from app.providers.enums import ProviderKey


# TODO: test the provider and include it in the PROVIDERS list
class FinanceProvider(NewsProvider):
    def __init__(self):
        super().__init__(
            key=ProviderKey.RTV.value,
            # key=ProviderKey.FINANCE.value,
            name="Finance.si",
            url="https://www.finance.si",
            rss_feeds=["https://delivery.trinityaudio.ai/v1/playlist/k280vh2z/rss"],
        )

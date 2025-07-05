from app.providers.news_provider import NewsProvider


class DemokracijaProvider(NewsProvider):
    def __init__(self):
        super().__init__(
            key="demokracija",
            name="Demokracija",
            url="https://demokracija.si/",
            rss_feeds=["https://demokracija.si/feed/"],
        )

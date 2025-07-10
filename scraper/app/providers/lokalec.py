from app.providers.news_provider import NewsProvider


class LokalecProvider(NewsProvider):
    def __init__(self):
        super().__init__(
            key="lokalec",
            name="Lokalec",
            url="https://www.lokalec.si",
            rss_feeds=["https://www.lokalec.si/feed/"],
        )

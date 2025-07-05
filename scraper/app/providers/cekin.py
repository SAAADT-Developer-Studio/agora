from scraper.app.providers.news_provider import NewsProvider


class CekinProvider(NewsProvider):
    def __init__(self):
        super().__init__(
            name="Cekin",
            url="https://cekin.si",
            rss_feeds=["https://cekin.si/rss"],
        )

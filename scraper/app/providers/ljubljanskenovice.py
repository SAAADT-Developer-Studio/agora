from scraper.app.providers.news_provider import NewsProvider


class LjNoviceProvider(NewsProvider):
    def __init__(self):
        super().__init__(
            name="Ljubljanske novice",
            url="https://ljnovice.si/",
            rss_feeds=["https://ljnovice.si/feed/"],
        )

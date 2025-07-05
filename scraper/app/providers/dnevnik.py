from app.providers.news_provider import NewsProvider


class DnevnikProvider(NewsProvider):
    def __init__(self):
        super().__init__(
            key="dnevnik",
            name="Dnevnik",
            url="https://www.dnevnik.si",
            rss_feeds=["https://www.dnevnik.si/rss.xml"],
        )

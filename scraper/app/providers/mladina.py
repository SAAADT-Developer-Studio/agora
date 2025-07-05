from app.providers.news_provider import NewsProvider


class MladinaProvider(NewsProvider):
    def __init__(self):
        super().__init__(
            key="mladina",
            name="Mladina",
            url="https://www.mladina.si",
            rss_feeds=["https://feeds.feedburner.com/Mladina"],
        )

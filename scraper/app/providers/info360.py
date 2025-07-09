from app.providers.news_provider import NewsProvider


class Info360Provider(NewsProvider):
    def __init__(self):
        super().__init__(
            key="info360",
            name="Info360",
            url="https://info360.si/",
            rss_feeds=["https://info360.si/rss.xml"],
        )

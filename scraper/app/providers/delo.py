from app.providers.news_provider import NewsProvider


class DeloProvider(NewsProvider):
    def __init__(self):
        super().__init__(
            key="delo",
            name="Delo",
            url="https://www.delo.si",
            rss_feeds=["https://www.delo.si/rss"],
        )

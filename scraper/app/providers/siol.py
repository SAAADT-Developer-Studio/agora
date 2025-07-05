from app.providers.news_provider import NewsProvider, ArticleMetadata


class SiolProvider(NewsProvider):
    def __init__(self):
        super().__init__(
            key="siol",
            name="Siol",
            url="https://siol.net",
            rss_feeds=["https://siol.net/feeds/latest"],
        )

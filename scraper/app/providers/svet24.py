from scraper.app.providers.news_provider import NewsProvider, ArticleMetadata


class Svet24Provider(NewsProvider):
    def __init__(self):
        super().__init__(
            name="Svet24",
            url="https://www.svet24.si",
            rss_feeds=["https://svet24.si/rss/site.xml"],
        )

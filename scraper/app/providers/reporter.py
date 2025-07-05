from scraper.app.providers.news_provider import NewsProvider, ArticleMetadata


class ReporterProvider(NewsProvider):
    def __init__(self):
        super().__init__(
            name="Reporter",
            url="https://reporter.si",
            rss_feeds=["https://reporter.si/rss/site.xml"],
        )

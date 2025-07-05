from scraper.app.providers.news_provider import NewsProvider, ArticleMetadata


class SloTechProvider(NewsProvider):
    def __init__(self):
        super().__init__(
            name="Slo-Tech",
            url="https://slo-tech.com",
            rss_feeds=["http://feeds.st.si/ST-novice"],
        )

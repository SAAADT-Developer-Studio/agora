from app.providers.news_provider import NewsProvider, ArticleMetadata


class SlovenskeNoviceProvider(NewsProvider):
    def __init__(self):
        super().__init__(
            key="slovenskenovice",
            name="Slovenske Novice",
            url="https://www.slovenskenovice.si",
            rss_feeds=["https://www.slovenskenovice.si/rss"],
        )

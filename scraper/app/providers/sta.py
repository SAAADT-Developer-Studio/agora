from app.providers.news_provider import NewsProvider, ArticleMetadata


class STAProvider(NewsProvider):
    def __init__(self):
        super().__init__(
            key="sta",
            name="Slovenska tiskovna agencija",
            url="https://www.sta.si",
            rss_feeds=["https://www.sta.si/rss-0"],
        )

from app.providers.news_provider import NewsProvider


class NecenzuriranoProvider(NewsProvider):
    def __init__(self):
        super().__init__(
            key="necenzurirano",
            name="Necenzurirano",
            url="https://necenzurirano.si",
            rss_feeds=["https://necenzurirano.si/rss/site.xml"],
        )

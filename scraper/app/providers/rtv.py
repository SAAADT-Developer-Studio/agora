from app.providers.news_provider import NewsProvider


class RTVProvider(NewsProvider):
    def __init__(self):
        super().__init__(
            key="rtv",
            name="RTV",
            url="https://www.rtvslo.si",
            rss_feeds=["https://img.rtvslo.si/feeds/00.xml"],
        )

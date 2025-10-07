from app.providers.news_provider import NewsProvider, ArticleMetadata
from app.providers.enums import ProviderKey


class SloTechProvider(NewsProvider):
    def __init__(self):
        super().__init__(
            key=ProviderKey.SLOTECH.value,
            name="Slo-Tech",
            url="https://slo-tech.com",
            rss_feeds=["http://feeds.st.si/ST-novice"],
        )

from app.providers.news_provider import NewsProvider
from app.providers.enums import ProviderKey


class SloTechProvider(NewsProvider):
    def __init__(self):
        super().__init__(
            key=ProviderKey.SLOTECH.value,
            name="Slo-Tech",
            url="https://slo-tech.com",
            rss_feeds=["http://feeds.st.si/ST-novice"],
        )

    def parse_rss_entry_image_urls(self, entry):
        media_content = entry.get("media_content")
        if media_content and len(media_content) > 0:
            image_urls = [
                item.get("url")
                for item in media_content
                if isinstance(item, dict) and "url" in item
            ]
            return [url for url in image_urls if isinstance(url, str)]
        return []

import logging

from app.providers.news_provider import NewsProvider, ArticleMetadata
from app.providers.enums import ProviderKey, BiasRating


class N1InfoProvider(NewsProvider):
    def __init__(self):
        super().__init__(
            key=ProviderKey.N1INFO.value,
            name="N1 Info",
            url="https://n1info.si",
            rss_feeds=["https://n1info.si/feed"],
            bias_rating=BiasRating.CENTER.value,
        )

    def parse_rss_entry_image_urls(self, entry: dict) -> list[str]:
        image_urls = []
        try:
            for media in entry.get("media_content", []):
                if media.get("type").startswith("image"):
                    image_urls.append(media.get("url"))
        except Exception as e:
            logging.error(f"Error extracting image URLs for n1info: {e}")
            return []

        return image_urls + super().parse_rss_entry_image_urls(entry)

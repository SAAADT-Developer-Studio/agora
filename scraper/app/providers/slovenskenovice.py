import logging
from app.providers.news_provider import NewsProvider, ArticleMetadata
from app.providers.enums import ProviderKey, BiasRating


class SlovenskeNoviceProvider(NewsProvider):
    def __init__(self):
        super().__init__(
            key=ProviderKey.SLOVENSKENOVICE.value,
            name="Slovenske Novice",
            url="https://www.slovenskenovice.si",
            rss_feeds=["https://www.slovenskenovice.si/rss"],
            bias_rating=BiasRating.CENTER_LEFT.value,
        )

    def parse_rss_entry_image_urls(self, entry: dict) -> list[str]:
        image_urls = super().parse_rss_entry_image_urls(entry)
        try:
            return [url.replace("width-660", "width-932", count=1) for url in image_urls]
        except Exception as e:
            logging.error(f"Error parsing image URLs for Slovenske Novice entry: {e}")
            return image_urls

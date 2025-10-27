from app.providers.news_provider import NewsProvider, ArticleMetadata
from app.providers.enums import ProviderKey, BiasRating
import logging


class DomovinaProvider(NewsProvider):
    def __init__(self):
        super().__init__(
            key=ProviderKey.DOMOVINA.value,
            name="Domovina",
            url="https://www.domovina.je",
            rss_feeds=["https://www.domovina.je/feed"],
            bias_rating=BiasRating.RIGHT.value,
        )

    def parse_rss_entry_image_urls(self, entry: dict) -> list[str]:
        image_urls = super().parse_rss_entry_image_urls(entry)
        try:
            return [url.replace("medium", "large", count=1) for url in image_urls]
        except Exception as e:
            logging.error(f"Error parsing image URLs for Domovina entry: {e}")
            return image_urls

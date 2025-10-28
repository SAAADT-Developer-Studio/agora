from app.providers.news_provider import NewsProvider
from app.providers.enums import ProviderKey, BiasRating
import logging

from app.utils.parse_description_image import parse_description_image


class DemokracijaProvider(NewsProvider):
    def __init__(self):
        super().__init__(
            key=ProviderKey.DEMOKRACIJA.value,
            name="Demokracija",
            url="https://demokracija.si/",
            rss_feeds=["https://demokracija.si/feed/"],
            bias_rating=BiasRating.RIGHT.value,
        )

    def parse_rss_entry_image_urls(self, entry: dict) -> list[str]:
        image_urls = []
        try:
            description = entry.get("summary", "") or entry.get("description", "")
            img_url = parse_description_image(description)
            if img_url:
                image_urls.append(img_url)
        except Exception as e:
            logging.error(f"Error extracting image URLs for 24ur: {e}")
            return []

        return image_urls

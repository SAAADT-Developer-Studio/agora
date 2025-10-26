import logging
import xmltodict
import httpx
import asyncio
from datetime import datetime, timedelta
import itertools
from bs4 import BeautifulSoup
from app import config

from app.providers.news_provider import NewsProvider, ArticleMetadata
from app.providers.enums import ProviderKey, BiasRating


class _24URProvider(NewsProvider):
    def __init__(self):
        super().__init__(
            key=ProviderKey._24UR.value,
            name="24ur",
            url="https://www.24ur.com",
            rss_feeds=["https://www.24ur.com/rss"],
            bias_rating=BiasRating.CENTER_LEFT.value,
        )

    def parse_rss_entry_image_urls(self, entry: dict) -> list[str]:
        image_urls = []

        try:
            description = entry.get("summary", "") or entry.get("description", "")

            if description:
                # Parse HTML description with BeautifulSoup
                soup = BeautifulSoup(description, "html.parser")
                img_tags = soup.find_all("img")

                for img in img_tags:
                    src = img.get("src")
                    if src:
                        # Replace 213xX with 884xX for higher quality
                        high_quality_url = src.replace("/213xX/", "/884xX/")
                        image_urls.append(high_quality_url)

            # Always add default enclosure extraction at the end
            image_urls.extend(super().parse_rss_entry_image_urls(entry))
        except Exception as e:
            logging.error(f"Error extracting image URLs for 24ur: {e}")
            return []

        return image_urls

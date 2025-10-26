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

# extract better quality image from descriptiom amd replace 213 with 884
# <description><img src="https://images.24ur.com/media/images/213xX/Oct2025/32e6f6cb52a810504230_63488961.png?v=034b&fop=fp:0.51:0.28" alt="www.24ur.com"/> V No


class _24URProvider(NewsProvider):
    def __init__(self):
        super().__init__(
            key=ProviderKey._24UR.value,
            name="24ur",
            url="https://www.24ur.com",
            rss_feeds=["https://www.24ur.com/rss"],
            bias_rating=BiasRating.CENTER_LEFT.value,
        )

    def extract_image_urls(self, entry: dict) -> list[str]:
        image_urls = []
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
        image_urls.extend(super().extract_image_urls(entry))

        return image_urls

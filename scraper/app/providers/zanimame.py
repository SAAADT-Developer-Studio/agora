from app.providers.news_provider import NewsProvider
from app.providers.enums import ProviderKey, BiasRating
from bs4 import BeautifulSoup

from app.utils.parse_description_image import parse_description_image


class ZanimaMeProvider(NewsProvider):
    def __init__(self):
        super().__init__(
            key=ProviderKey.ZANIMAME.value,
            name="Zanima.me",
            url="https://www.zanima.me",
            rss_feeds=["https://www.zanima.me/feed/"],
            bias_rating=BiasRating.RIGHT.value,  # i guess?
        )

    def parse_rss_entry_image_urls(self, entry: dict) -> list[str]:
        description = entry.get("summary", "") or entry.get("description", "")
        img_url = parse_description_image(description)
        if img_url:
            return [img_url]
        return []

    def extract_image_urls_from_html(self, html):
        soup = BeautifulSoup(html, "html.parser")
        img = soup.select_one("div.featured-image img")
        return [img["src"]] if img and img.get("src") else []

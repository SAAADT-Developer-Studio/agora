import xmltodict
import httpx
import asyncio
from datetime import datetime
import itertools
from bs4 import BeautifulSoup
import logging

from app.providers.news_provider import NewsProvider, ArticleMetadata, ExtractedArticle
from app.providers.enums import ProviderKey, BiasRating


class Maribor24Provider(NewsProvider):
    def __init__(self):
        super().__init__(
            key=ProviderKey.MARIBOR24.value,
            name="Maribor24",
            url="https://maribor24.si",
            rss_feeds=["https://maribor24.si/feed"],
            bias_rating=BiasRating.CENTER_RIGHT.value,
        )

    async def extract_article(self, url: str) -> ExtractedArticle:
        html = await self.fetch_article_html(url)
        extracted_article = self.extract_article_from_html(html, url)

        try:
            extracted_article.image_urls = self.extract_image_urls(html)
        except Exception as e:
            logging.error(f"Error extracting images from {url}: {e}")

        return extracted_article

    def extract_image_urls(self, html: str) -> list[str]:
        soup = BeautifulSoup(html, "html.parser")
        image_urls: list[str] = []

        # Find the main article image
        article_picture = soup.select_one("picture.article-main-img")
        if article_picture:
            img = article_picture.select_one("img")
            if img:
                src = img.get("src")
                if src and isinstance(src, str):
                    image_urls.append(src)

        return image_urls

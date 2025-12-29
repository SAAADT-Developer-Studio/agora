from bs4 import BeautifulSoup

from app.providers.news_provider import NewsProvider
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

    def extract_image_urls_from_html(self, html: str) -> list[str]:
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

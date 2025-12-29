from bs4 import BeautifulSoup, Tag

from app.providers.news_provider import NewsProvider
from app.providers.enums import ProviderKey, BiasRating


class LokalecProvider(NewsProvider):
    def __init__(self):
        super().__init__(
            key=ProviderKey.LOKALEC.value,
            name="Lokalec",
            url="https://www.lokalec.si",
            rss_feeds=["https://www.lokalec.si/feed/"],
            bias_rating=BiasRating.CENTER.value,
        )

    def extract_image_urls_from_html(self, html: str) -> list[str]:
        image_urls: list[str] = []
        soup = BeautifulSoup(html, "html.parser")
        
        figure = soup.find("figure", class_="wp-caption")
        if figure:
            img = figure.find("img")
            if isinstance(img, Tag):
                src = img.get("src")
                if isinstance(src, str):
                    image_urls.append(src)
        
        return image_urls

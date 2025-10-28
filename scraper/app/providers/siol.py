from bs4 import BeautifulSoup
from app.providers.news_provider import NewsProvider, ArticleMetadata, ExtractedArticle
from app.providers.enums import ProviderKey, BiasRating


class SiolProvider(NewsProvider):
    def __init__(self):
        super().__init__(
            key=ProviderKey.SIOL.value,
            name="Siol",
            url="https://siol.net",
            rss_feeds=["https://siol.net/feeds/latest"],
            bias_rating=BiasRating.CENTER.value,
        )

    def extract_image_urls_from_html(self, html: str) -> list[str]:
        soup = BeautifulSoup(html, "html.parser")
        image_urls: list[str] = []

        # Find the main article image
        article_figure = soup.select_one(".article_main_media__main_image_figure")
        if article_figure:
            # Try to get the highest resolution image from the lightbox trigger
            lightbox_div = article_figure.select_one(
                ".article_main_media__main_image_lightbox_trigger"
            )
            if lightbox_div:
                data_href = lightbox_div.get("data-href")
                if data_href and isinstance(data_href, str):
                    image_url = data_href
                    if not image_url.startswith("http"):
                        image_url = f"https://siol.net{image_url}"
                    image_urls.append(image_url)
            else:
                # Fallback to picture source or img tag
                picture = article_figure.select_one("picture")
                if picture:
                    # Try to get the first source srcset (highest resolution)
                    source = picture.select_one("source")
                    if source:
                        srcset = source.get("srcset")
                        if srcset and isinstance(srcset, str):
                            image_url = srcset
                            if not image_url.startswith("http"):
                                image_url = f"https://siol.net{image_url}"
                            image_urls.append(image_url)
                    else:
                        # Fallback to img tag
                        img = picture.select_one("img")
                        if img:
                            src = img.get("src")
                            if src and isinstance(src, str):
                                image_url = src
                                if not image_url.startswith("http"):
                                    image_url = f"https://siol.net{image_url}"
                                image_urls.append(image_url)
        return image_urls

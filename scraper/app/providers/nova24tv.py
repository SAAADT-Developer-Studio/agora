from bs4 import BeautifulSoup, Tag

from app.providers.news_provider import NewsProvider
from app.providers.enums import ProviderKey, BiasRating


# category sitemap https://nova24tv.si/category-sitemap.xml


class Nova24TVProvider(NewsProvider):
    def __init__(self):
        super().__init__(
            key=ProviderKey.NOVA24TV.value,
            name="Nova24TV",
            url="https://nova24tv.si",
            rss_feeds=["https://nova24tv.si/feed"],
            bias_rating=BiasRating.RIGHT.value,
        )

    def extract_image_urls_from_html(self, html: str) -> list[str]:
        image_urls: list[str] = []
        soup = BeautifulSoup(html, "html.parser")

        img = soup.find("img", class_="entry-thumb")
        if isinstance(img, Tag):
            srcset = img.get("srcset")
            if isinstance(srcset, str):
                # Parse srcset to find the highest resolution image
                sources = [s.strip().split() for s in srcset.split(",")]
                if sources:
                    # Get the first URL (which is the highest quality - 8192w in this case)
                    highest_quality_url = sources[0][0]
                    image_urls.append(highest_quality_url)

        return image_urls

from app.providers.news_provider import NewsProvider
from app.providers.enums import ProviderKey, BiasRating
from app.utils.parse_description_image import parse_description_image


class MladinaProvider(NewsProvider):
    def __init__(self):
        super().__init__(
            key=ProviderKey.MLADINA.value,
            name="Mladina",
            url="https://www.mladina.si",
            rss_feeds=["https://www.mladina.si/media/rss/rss-fb-mladina.xml"],
            # Thu, 3 Jul 2025 22:00:00 GMT
            rss_date_format="%a, %d %b %Y %H:%M:%S %Z",
            bias_rating=BiasRating.LEFT.value,
            time_window={"hours": 20},
        )

    def parse_rss_entry_image_urls(self, entry):
        description = entry.get("summary", "") or entry.get("description", "")
        img_url = parse_description_image(description)
        if img_url:
            return [img_url.replace("__190", "__1600")]
        return []

from app.providers.news_provider import NewsProvider
from app.providers.enums import ProviderKey, BiasRating
from app.utils.parse_description_image import parse_description_image


class STAProvider(NewsProvider):
    def __init__(self):
        super().__init__(
            key=ProviderKey.STA.value,
            name="Slovenska tiskovna agencija",
            url="https://www.sta.si",
            rss_feeds=["https://www.sta.si/rss-0"],
            bias_rating=BiasRating.CENTER.value,
        )

    def parse_rss_entry_image_urls(self, entry: dict) -> list[str]:
        description = entry.get("summary", "") or entry.get("description", "")
        img_url = parse_description_image(description)
        if img_url:
            return [img_url]
        return []

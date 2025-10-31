from app.providers.news_provider import NewsProvider
from app.providers.enums import ProviderKey
from app.utils.parse_description_image import parse_description_image
from app.utils.remove_query_params import remove_query_params


class LjNoviceProvider(NewsProvider):
    def __init__(self):
        super().__init__(
            key=ProviderKey.LJUBLJANSKENOVICE.value,
            name="Ljubljanske novice",
            url="https://ljnovice.si/",
            rss_feeds=["https://ljnovice.si/feed/"],
        )

    def parse_rss_entry_image_urls(self, entry):
        content = entry.get("content")
        if content:
            image_url = parse_description_image(content[0].value)
            if image_url:
                image_url = remove_query_params(image_url)
                return [image_url]
        return []

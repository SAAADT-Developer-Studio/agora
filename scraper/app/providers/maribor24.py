import xmltodict
import httpx
import asyncio
from datetime import datetime
import itertools

from app.providers.news_provider import NewsProvider, ArticleMetadata
from app.providers.keys import ProviderKey


class Maribor24Provider(NewsProvider):
    def __init__(self):
        super().__init__(
            key=ProviderKey.MARIBOR24.value,
            name="Maribor24",
            url="https://maribor24.si",
            rss_feeds=["https://maribor24.si/feed"],
        )

    # async def fetch_articles(self) -> list[ArticleMetadata]:
    #     async with httpx.AsyncClient() as client:
    #         response = await client.get(f"{self.url}/sitemap.xml")
    #         document = xmltodict.parse(response.text)
    #         sitemaps = [
    #             sitemap["loc"]
    #             for sitemap in document["sitemapindex"]["sitemap"]
    #             if sitemap["loc"].startswith("https://maribor24.si/sitemap-articles")
    #         ]

    #         second_last_page, last_page = sitemaps[-2:]
    #         results = await asyncio.gather(
    #             self.fetch_page_articles(last_page),
    #             self.fetch_page_articles(second_last_page),
    #         )
    #         urls = list(itertools.chain(*results))
    #         return urls

    # @staticmethod
    # async def fetch_page_articles(url: str) -> list[ArticleMetadata]:
    #     async with httpx.AsyncClient() as client:
    #         response = await client.get(url)
    #         document = xmltodict.parse(response.text)
    #         articles = document["urlset"]["url"]
    #         urls = []
    #         for article in articles:
    #             url = article["loc"]
    #             last_mod = datetime.fromisoformat(article["lastmod"])
    #             urls.append(url)
    #         return urls

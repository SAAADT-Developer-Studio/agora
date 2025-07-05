import xmltodict
import httpx
import asyncio
from datetime import datetime, timedelta
import itertools
from app import config

from app.providers.news_provider import NewsProvider, ArticleMetadata


class _24URProvider(NewsProvider):
    def __init__(self):
        super().__init__(
            key="24ur",
            name="24ur",
            url="https://www.24ur.com",
            rss_feeds=["https://www.24ur.com/rss"],
        )

    # async def fetch_articles(self) -> list[ArticleMetadata]:
    #     async with httpx.AsyncClient() as client:
    #         response = await client.get("https://www.24ur.com/sitemaps/sites/1")
    #         document = xmltodict.parse(response.text)
    #         second_last_page, last_page = document["sitemapindex"]["sitemap"][-2:]

    #         results = await asyncio.gather(
    #             self.fetch_page_articles(last_page["loc"]),
    #             self.fetch_page_articles(second_last_page["loc"]),
    #         )
    #         urls = list(itertools.chain(*results))
    #         return urls

    # async def fetch_page_articles(self, url: str) -> list[ArticleMetadata]:
    #     async with httpx.AsyncClient() as client:
    #         response = await client.get(url)
    #         document = xmltodict.parse(response.text)
    #         articles = document["urlset"]["url"]
    #         urls = []
    #         for article in articles:
    #             url = article["loc"]
    #             last_mod = datetime.fromisoformat(article["lastmod"])
    #             if last_mod > datetime.now(last_mod.tzinfo) - timedelta(
    #                 **config.TIME_WINDOW
    #             ):
    #                 urls.append(
    #                     ArticleMetadata(
    #                         link=url,
    #                         published_at=last_mod,
    #                     )
    #                 )
    #         return urls

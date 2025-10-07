from app.providers.news_provider import NewsProvider, ArticleMetadata
from app.providers.enums import ProviderKey, BiasRating

from datetime import datetime
import xmltodict
import httpx

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

    # async def fetch_articles(self) -> list[ArticleMetadata]:
    #     url = f"{self.url}/post-sitemap.xml"
    #     async with httpx.AsyncClient() as client:
    #         client.headers["User-Agent"] = (
    #             "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3"
    #         )
    #         response = await client.get(url)
    #         document = xmltodict.parse(response.text)
    #         article_docs = document["urlset"]["url"]
    #         articles: list[ArticleMetadata] = []
    #         for article in article_docs:
    #             article_url: str = article["loc"]
    #             last_mod = datetime.fromisoformat(article["lastmod"])
    #             articles.append(
    #                 ArticleMetadata(
    #                     link=article_url,
    #                     published_at=last_mod,
    #                 )
    #             )
    #         return articles

from datetime import datetime
import xmltodict
import httpx


from app.providers.news_provider import NewsProvider, ArticleMetadata


class N1InfoProvider(NewsProvider):
    def __init__(self):
        super().__init__(
            key="n1info",
            name="N1 Info",
            url="https://n1info.si",
            rss_feeds=["https://n1info.si/feed"],
        )

    # async def fetch_articles(self) -> list[ArticleMetadata]:
    #     url = f"{self.url}/sitemap/sitemap_n1infoslovenia_post_1.xml"
    #     async with httpx.AsyncClient() as client:
    #         response = await client.get(url)
    #         document = xmltodict.parse(response.text)
    #         articles = document["urlset"]["url"]
    #         urls: list[ArticleMetadata] = []
    #         for article in articles:
    #             article_url: str = article["loc"]
    #             last_mod = datetime.fromisoformat(article["lastmod"])
    #             urls.append(
    #                 ArticleMetadata(
    #                     link=article_url,
    #                     published_at=last_mod,
    #                 )
    #             )
    #         return articles

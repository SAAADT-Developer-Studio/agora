import xmltodict
import httpx

from scraper.app.providers.news_provider import NewsProvider, ArticleMetadata


class PlanetTVProvider(NewsProvider):
    def __init__(self):
        super().__init__(
            name="N1 Info",
            url="https://www.planet-tv.si",
            rss_feeds=["https://www.planet-tv.si/rss"],
        )

    # async def fetch_articles(self) -> list[ArticleMetadata]:
    #     url = f"{self.url}/rss"
    #     async with httpx.AsyncClient() as client:
    #         # client.headers["User-Agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3"
    #         response = await client.get(url)
    #         document = xmltodict.parse(response.text)
    #         articles = document["rss"]["channel"]["item"]
    #         urls = []
    #         for article in articles[-10:]:
    #             article_url = f"{self.url}{article["link"]["@href"]}"
    #             urls.append(article_url)
    #         return urls

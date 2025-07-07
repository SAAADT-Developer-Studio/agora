from datetime import datetime, timedelta
import httpx


from app.providers.news_provider import NewsProvider, ArticleMetadata


class VecerProvider(NewsProvider):
    def __init__(self):
        super().__init__(
            key="vecer",
            name="Večer",
            url="https://vecer.com",
            rss_feeds=["https://feeds.feedburner.com/vecer"],
        )

    # async def fetch_articles(self) -> list[ArticleMetadata]:
    #     start_date = (datetime.now() - timedelta(days=1)).date()
    #     end_date = datetime.now().date()
    #     page_size = 50
    #     url = f"{self.url}/rubrika/danes-objavljeno/1/{page_size}/{start_date} 00:00:00/{end_date} 23:59:59"
    #     async with httpx.AsyncClient() as client:
    #         response = await client.get(url)
    #         articles = response.json()
    #         urls = []
    #         for article in articles:
    #             article_url = f"{self.url}{article["url"]}"
    #             date = datetime.fromisoformat(article["published"])
    #             urls.append(
    #                 ArticleMetadata(
    #                     link=article_url,
    #                     published_at=date,
    #                     provider_key=self.key,
    #                 )
    #             )
    #         return urls

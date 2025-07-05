from datetime import datetime
from app.extractor.crawl4ai import extract


from app.providers.news_provider import NewsProvider, ArticleMetadata


class PrimorskeNoviceProvider(NewsProvider):
    def __init__(self):
        super().__init__(
            key="primorskenovice",
            name="Primorske Novice",
            url="https://primorske.svet24.si",
            rss_feeds=["https://www.planet-tv.si/rss"],
        )

    # TODO: handle edge case of articles that are not in the current year
    async def fetch_articles(self) -> list[ArticleMetadata]:
        current_year = datetime.now().year
        url = f"{self.url}/{current_year}"
        schema = {
            "name": "Article urls",
            "baseSelector": ".article-medium",
            "fields": [
                {
                    "name": "article_path",
                    "selector": "a.image-link",
                    "type": "attribute",
                    "attribute": "href",
                },
                {
                    "name": "date",
                    "selector": ".article-published",
                    "type": "attribute",
                    "attribute": "datetime",
                },
            ],
        }
        data = await extract(url, schema)
        articles = []
        for article in data:
            date = datetime.strptime(article["date"], "%Y-%m-%dT%H:%M:%S")
            link = f"{self.url}{article['article_path']}"
            articles.append(
                ArticleMetadata(
                    link=link,
                    published_at=date,
                )
            )
        return articles

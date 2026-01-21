import httpx
import feedparser
from app.providers.news_provider import NewsProvider, ArticleMetadata
from app.providers.enums import ProviderKey, BiasRating


class PrimorskeNoviceProvider(NewsProvider):
    def __init__(self):
        super().__init__(
            key=ProviderKey.PRIMORSKENOVICE.value,
            name="Primorske Novice",
            url="https://primorske.svet24.si",
            rss_feeds=["https://primorske.svet24.si/rss.xml"],
            bias_rating=BiasRating.CENTER_LEFT.value,
        )

    async def fetch_rss_feed(
        self, client: httpx.AsyncClient, feed_url: str
    ) -> list[ArticleMetadata]:
        client.follow_redirects = True
        client.headers["User-Agent"] = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        )
        response = await client.get(feed_url)
        response.raise_for_status()
        feed = feedparser.parse(response.text)

        articles = []
        for entry in feed["entries"]:
            articles.append(self.parse_rss_feed_entry(entry))
        return articles

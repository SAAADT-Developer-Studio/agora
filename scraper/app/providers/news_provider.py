from abc import ABC, abstractmethod
import httpx
import feedparser
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
import logging


@dataclass
class ArticleMetadata:
    """Metadata for an article."""

    link: str
    published_at: datetime = field(default_factory=datetime.now)
    title: Optional[str] = None
    summary: Optional[str] = None


class NewsProvider(ABC):
    """Abstract base class for news providers."""

    def __init__(
        self,
        key: str,
        name: str,
        url: str,
        rss_feeds: list[str],
    ):
        self.key = key
        self.name = name
        self.url = url
        self.rss_feeds = rss_feeds

    async def fetch_articles(self) -> list[ArticleMetadata]:
        """
        Fetch articles from the provider's RSS feed.

        Returns:
            A list of article metadata.
        """
        articles = []
        async with httpx.AsyncClient() as client:
            for feed_url in self.rss_feeds:
                try:
                    articles.extend(await self.fetch_rss_feed(client, feed_url))
                except Exception as e:
                    logging.error(f"Error fetching RSS feed {feed_url}: {e}")
        return articles

    async def fetch_rss_feed(
        self, client: httpx.AsyncClient, feed_url: str
    ) -> list[ArticleMetadata]:
        client.follow_redirects = True
        response = await client.get(feed_url)
        feed = feedparser.parse(response.text)

        articles = []
        for entry in feed["entries"]:
            date = datetime.now()
            if "published" in entry:
                date = datetime.strptime(entry["published"], "%a, %d %b %Y %H:%M:%S %z")
            entry["summary"] = entry.get("summary")
            entry["title"] = entry["title"]
            articles.append(
                ArticleMetadata(
                    title=entry["title"],
                    link=entry["link"],
                    published_at=date,
                    summary=entry["summary"],
                )
            )
        return articles

    def get_link(self, link: str) -> str:
        """
        Get the full link for an article.

        Args:
            link: The relative or absolute link to the article.

        Returns:
            The full URL of the article.
        """
        if link.startswith("http"):
            return link
        return f"{self.url}{link}"

from abc import ABC, abstractmethod
import httpx
import feedparser
from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class ArticleMetadata:
    """Metadata for an article."""

    link: str
    published_at: datetime
    title: Optional[str] = None
    summary: Optional[str] = None


class NewsProvider(ABC):
    """Abstract base class for news providers."""

    def __init__(
        self,
        name: str,
        url: str,
        rss_feeds: list[str],
    ):
        self.name = name
        self.url = url
        self.rss_feeds = rss_feeds

    async def fetch_articles(self) -> list[ArticleMetadata]:
        """
        Fetch articles from the provider's RSS feed.

        Returns:
            A list of article URLs.
        """
        async with httpx.AsyncClient() as client:
            client.follow_redirects = True
            response = await client.get(self.url)
            feed = feedparser.parse(response.text)
            articles = []
            for entry in feed["entries"]:
                link = entry.get("link", "")
                date = datetime.now()
                if "published" in entry:
                    date = datetime.strptime(
                        entry["published"], "%a, %d %b %Y %H:%M:%S %z"
                    )
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

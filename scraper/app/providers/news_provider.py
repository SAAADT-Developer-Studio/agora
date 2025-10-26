from abc import ABC, abstractmethod
import httpx
import feedparser
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
import logging
from pydantic import BaseModel, Field
from readability import parse


@dataclass
class ArticleMetadata:
    """Metadata for an article."""

    link: str
    provider_key: str
    image_urls: list[str]
    published_at: datetime = field(default_factory=datetime.now)
    title: Optional[str] = None
    summary: Optional[str] = None


class ExtractedArticle(BaseModel):
    """Class representing an article with its attributes."""

    url: str = Field(description="URL of the article")
    title: str = Field(description="Title of the article")
    author: str | None = Field(description="Author of the article", default=None)
    deck: str = Field(description="Deck of the article, a summary or brief description")
    content: str = Field(description="Full content of the article")
    published_at: str | None = Field(
        description="Date when the article was published", default=None
    )
    image_urls: list[str] = Field(description="List of image URLs in the article", default=[])


class NewsProvider(ABC):
    """Abstract base class for news providers."""

    def __init__(
        self,
        key: str,
        name: str,
        url: str,
        rss_feeds: list[str],
        rss_date_format: str = "%a, %d %b %Y %H:%M:%S %z",
        rank: int = 0,
        bias_rating: Optional[str] = None,
    ):
        self.key = key
        self.name = name
        self.url = url
        self.rss_feeds = rss_feeds
        self.rss_date_format = rss_date_format
        self.rank = rank
        self.bias_rating = bias_rating

    async def fetch_articles(self) -> list[ArticleMetadata]:
        articles: list[ArticleMetadata] = []
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
        response.raise_for_status()
        feed = feedparser.parse(response.text)

        articles = []
        for entry in feed["entries"]:
            articles.append(self.parse_rss_feed_entry(entry))
        return articles

    def parse_rss_feed_entry(self, entry: dict) -> ArticleMetadata:
        date = datetime.now()
        if "published" in entry:
            date = datetime.strptime(entry["published"], self.rss_date_format)
        entry["summary"] = entry.get("summary")
        image_urls = self.parse_rss_entry_image_urls(entry)

        return ArticleMetadata(
            title=entry["title"],
            link=self.get_link(entry["link"]),
            published_at=date,
            summary=entry["summary"],
            provider_key=self.key,
            image_urls=image_urls,
        )

    def parse_rss_entry_image_urls(self, entry: dict) -> list[str]:
        return [enclosure["href"] for enclosure in entry.get("enclosures", [])]

    def get_link(self, link: str) -> str:
        if link.startswith("http"):
            return link
        return f"{self.url}{link}"

    async def fetch_article_html(self, url: str) -> str:
        async with httpx.AsyncClient() as client:
            client.follow_redirects = True
            # set user agent to avoid cloudflare blocking user agent
            client.headers["User-Agent"] = (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3"
            )

            response = await client.get(url)
            response.raise_for_status()
            return response.text

    def extract_article_from_html(self, html: str, url: str) -> ExtractedArticle:
        doc = parse(html)

        return ExtractedArticle(
            title=doc.title,
            deck=doc.excerpt,
            content=doc.text_content,
            author=doc.byline,
            url=url,
            published_at=doc.published_time,
        )

    async def extract_article(self, url: str) -> ExtractedArticle:
        html = await self.fetch_article_html(url)
        return self.extract_article_from_html(html, url)

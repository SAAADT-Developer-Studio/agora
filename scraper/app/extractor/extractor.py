from abc import ABC, abstractmethod
from pydantic import BaseModel, Field
import httpx


class ExtractedArticle(BaseModel):
    """Class representing an article with its attributes."""

    url: str = Field(description="URL of the article")
    title: str = Field(description="Title of the article")
    author: str = Field(description="Author of the article")
    deck: str = Field(description="Deck of the article, a summary or brief description")
    content: str = Field(description="Full content of the article")
    published_at: str = Field(description="Date when the article was published")


class Extractor(ABC):
    @abstractmethod
    async def extract_article(self, url: str) -> ExtractedArticle:
        pass

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

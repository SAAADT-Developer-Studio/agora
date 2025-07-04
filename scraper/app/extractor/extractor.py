from abc import ABC, abstractmethod
from pydantic import BaseModel, Field


class Article(BaseModel):
    """Class representing an article with its attributes."""

    title: str = Field(description="Title of the article")
    author: str = Field(description="Author of the article")
    deck: str = Field(description="Deck of the article, a summary or brief description")
    content: str = Field(description="Full content of the article")
    num_comments: int = Field(
        description="Number of comments on the article", default=0
    )
    is_error: bool = False


class Extractor(ABC):
    @abstractmethod
    async def extract_article(self, url: str) -> Article:
        pass

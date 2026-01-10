from typing import cast
from langchain_core.embeddings import Embeddings
from langchain.chat_models import init_chat_model
from pydantic import BaseModel, Field
from langchain_core.language_models import LanguageModelInput

from app.providers.news_provider import ExtractedArticle, ArticleMetadata
from app import config


class ArticleAnalysis(BaseModel):
    """Structured output for article analysis by LLM."""

    summary: str = Field(description="The summary of the article in Slovenian")
    rank: int = Field(description="The importance rank of the article from 1 to 10")
    categories: list[str] = Field(
        description="At most 3 applicable categories from the predefined list"
    )
    stock_image_search: str = Field(
        description="A short, general concept in English suitable for finding a relevant "
        "stock image. Avoid specific people, places, brands, or details. "
        "Example: 'business meeting', 'summer landscape', 'voting'."
    )
    is_paywalled: bool = Field(
        description=(
            "Whether access to the full article content requires payment. "
            "Do not set to true if the article is temporarily unlocked, "
            "fully visible, or just urges you to subscribe."
        )
    )


async def analyze_articles(
    article_metadatas: list[ArticleMetadata], extracted_articles: list[ExtractedArticle | None]
) -> list[ArticleAnalysis]:
    base_model = init_chat_model("gemini-2.0-flash", model_provider="google_genai")
    model = base_model.with_structured_output(ArticleAnalysis)

    inputs: list[LanguageModelInput] = []
    for article_metadata, extracted_article in zip(article_metadatas, extracted_articles):
        summary = f"Summary: {article_metadata.summary}" if article_metadata.summary else ""
        deck = (
            f"Deck: {extracted_article.deck}"
            if extracted_article and extracted_article.deck
            else ""
        )
        content = (
            f"Content: {extracted_article.content}"
            if extracted_article and extracted_article.content
            else ""
        )
        prompt: str = (
            "You are a professional Slovenian journalist.\n"
            "Write a concise summary (max 3 sentences) of the following article in Slovenian.\n"
            "Then, categorize the article into at most 3 categories from this predefined list. Order them by relevance. \n"
            "Also provide a rank from 1 to 10 for the article, based on the significance of its content to a Slovenian, who is interested in politics, economics or crime.\n"
            "Rank superflous content, like the horoscopes lower, and more important content, like controversial politics, crime, economics or local news higher.\n"
            f"{", ".join(category.key for category in config.CATEGORIES)} \n"
            f"Use only the provided categories, do not make up new ones.\n"
            f"Title: {article_metadata.title}\n"
            f"Published at: {article_metadata.published_at}\n"
            f"{summary}\n"
            f"{deck}\n"
            f"{content}"
        )
        inputs.append(prompt)
    results = await model.abatch(inputs=inputs)
    return cast(list[ArticleAnalysis], results)


async def generate_embeddings(
    article_metadatas: list[ArticleMetadata],
    analyses: list[ArticleAnalysis],
    embeddings: Embeddings,
) -> list[list[float]]:
    documents = [
        f"{article.title}\n{analysis.summary}"
        for article, analysis in zip(article_metadatas, analyses)
    ]
    article_embeddings = await embeddings.aembed_documents(documents)
    return article_embeddings

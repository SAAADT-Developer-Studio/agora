import asyncio
import time
import logging
from langchain_core.embeddings import Embeddings
from langchain.chat_models import init_chat_model
from pprint import pprint
from tenacity import retry, stop_after_attempt, wait_exponential
from pydantic import BaseModel, Field

from app.providers.news_provider import ExtractedArticle, ArticleMetadata, NewsProvider
from app.providers.providers import PROVIDERS
from app.database.schema import Article
from app.database.unit_of_work import database_session
from app.database.services import ArticleService
from app.feeds.fetch_articles import fetch_articles
from app.utils.concurrency import run_concurrently_with_limit
from app.utils.pexels import search_pexels_image
from app.clusterer.run_clustering import run_clustering
from app import config


async def process(
    providers: list[str] | None,
    embeddings: Embeddings,
):
    start_time = time.perf_counter()
    article_metadatas = await fetch_articles(providers)

    providers_map = {provider.key: provider for provider in PROVIDERS}

    with database_session() as uow:
        article_urls = [article_metadata.link for article_metadata in article_metadatas]
        existing_urls = uow.articles.get_by_urls(article_urls)

        new_article_metadatas: list[ArticleMetadata] = [
            article_metadata
            for article_metadata in article_metadatas
            if article_metadata.link not in existing_urls
        ]

        logging.info(f"Found {len(new_article_metadatas)} new articles")

        tasks = [
            extract_article(article_metadata, providers_map[article_metadata.provider_key])
            for article_metadata in new_article_metadatas
        ]
        extracted_articles, _ = await run_concurrently_with_limit(tasks, limit=3)

        article_analyses = await analyze_articles(new_article_metadatas, extracted_articles)

        articles_embeddings, stock_image_urls = await asyncio.gather(
            generate_embeddings(new_article_metadatas, article_analyses, embeddings),
            search_stock_images(new_article_metadatas, extracted_articles, article_analyses),
        )

        articles: list[Article] = []
        for (
            article_metadata,
            extracted_article,
            article_analysis,
            embedding,
            stock_image_url,
        ) in zip(
            new_article_metadatas,
            extracted_articles,
            article_analyses,
            articles_embeddings,
            stock_image_urls,
        ):
            image_urls = (
                extracted_article.image_urls if extracted_article else []
            ) + article_metadata.image_urls
            if not image_urls and stock_image_url:
                image_urls = [stock_image_url]

            article = Article(
                url=article_metadata.link,
                title=article_metadata.title
                or (extracted_article.title if extracted_article else ""),
                author=extracted_article.author if extracted_article else None,
                deck=extracted_article.deck if extracted_article else None,
                content=extracted_article.content if extracted_article else None,
                summary=article_analysis.summary,
                llm_rank=article_analysis.rank,
                published_at=article_metadata.published_at,
                embedding=embedding,
                news_provider_key=article_metadata.provider_key,
                image_urls=image_urls,
                categories=article_analysis.categories[:3],
                is_paywalled=article_analysis.is_paywalled,
            )
            pprint(article)
            articles.append(article)
        # TODO: error handling
        ArticleService.bulk_create_articles(articles, uow)

        uow.commit()
        uow.session.flush()

        await run_clustering(uow)

        end_time = time.perf_counter()
        logging.info(
            f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Successfully processed {len(articles)} new articles in {(end_time - start_time):.3f} seconds!"
        )


@retry(
    stop=stop_after_attempt(2),
    wait=wait_exponential(multiplier=1, min=1, max=10),
)
async def extract_article(
    article_metadata: ArticleMetadata, provider: NewsProvider
) -> ExtractedArticle | None:
    logging.info(f"Extracting article: {article_metadata.link}")
    try:
        return await provider.extract_article(article_metadata.link)
    except Exception as e:
        logging.error(f"Error extracting article from {article_metadata.link}: {e}")
        return None


class ArticleAnalysis(BaseModel):
    """Always use this tool to structure your response to the user."""

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
            "fully visible, or available without payment."
        )
    )


async def analyze_articles(
    article_metadatas: list[ArticleMetadata], extracted_articles: list[ExtractedArticle | None]
) -> list[ArticleAnalysis]:
    base_model = init_chat_model("gemini-2.0-flash", model_provider="google_genai")
    model = base_model.with_structured_output(ArticleAnalysis)

    inputs = []
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
        prompt = (
            "You are a professional Slovenian journalist.\n"
            "Write a concise summary (max 3 sentences) of the following article in Slovenian.\n"
            "Then, categorize the article into at most 3 categories from this predefined list. Order them by relevance. \n"
            "Also provide a rank from 1 to 10 for the article, based on the significance of its content to a Slovenian, who is interested in politics, economics or crime.\n",
            "Rank superflous content, like the horoscopes lower, and more important content, like controversial politics, crime, economics or anything with money higher.\n",
            f"{", ".join(category.key for category in config.CATEGORIES)} \n"
            f"Use only the provided categories, do not make up new ones.\n"
            f"Title: {article_metadata.title}\n"
            f"Published at: {article_metadata.published_at}\n"
            f"{summary}\n"
            f"{deck}\n"
            f"{content}",
        )
        inputs.append(prompt)
    results = await model.abatch(inputs=inputs)
    return results


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


async def search_stock_images(
    article_metadatas: list[ArticleMetadata],
    extracted_articles: list[ExtractedArticle | None],
    analyses: list[ArticleAnalysis],
) -> list[str | None]:
    tasks = []
    for article_metadata, extracted_article, analysis in zip(
        article_metadatas, extracted_articles, analyses
    ):
        # Check if article has any images
        extracted_imgs = extracted_article.image_urls if extracted_article else []
        metadata_imgs = article_metadata.image_urls or []
        has_images = len(extracted_imgs) > 0 or len(metadata_imgs) > 0

        # Search only if no images exist
        if not has_images:
            tasks.append(search_pexels_image(analysis.stock_image_search))
        else:
            tasks.append(asyncio.sleep(0, result=None))

    results = await asyncio.gather(*tasks, return_exceptions=True)
    return [None if isinstance(r, BaseException) else r for r in results]

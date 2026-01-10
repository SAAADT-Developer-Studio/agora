import asyncio
import time
import logging
from langchain_core.embeddings import Embeddings
from langchain.chat_models import BaseChatModel
from pprint import pprint
from tenacity import retry, stop_after_attempt, wait_exponential

from app.pipeline.discover_articles import discover_articles
from app.pipeline.analyzer import (
    analyze_articles,
    generate_embeddings,
)
from app.pipeline.images import search_stock_images
from app.providers.news_provider import ExtractedArticle, ArticleMetadata, NewsProvider
from app.providers.providers import PROVIDERS
from app.database.schema import Article
from app.database.unit_of_work import database_session
from app.database.services import ArticleService
from app.utils.concurrency import run_concurrently_with_limit
from app.clusterer.run_clustering import run_clustering


async def process(
    providers: list[str] | None,
    embeddings: Embeddings,
    analysis_model: BaseChatModel,
):

    start_time = time.perf_counter()
    article_metadatas = await discover_articles(providers)

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
        extracted_articles, _ = await run_concurrently_with_limit(tasks, limit=4)

        article_analyses = await analyze_articles(
            new_article_metadatas, extracted_articles, analysis_model
        )

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

        await run_clustering(uow, analysis_model)

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

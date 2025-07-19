import asyncio
import time
import logging
from langchain_core.embeddings import Embeddings
from langchain.chat_models import init_chat_model
from pprint import pprint
from tenacity import retry, stop_after_attempt, wait_exponential

from app.extractor.extractor import Extractor, ExtractedArticle
from scraper.app.database.schema import Article
from app.database.unit_of_work import database_session
from app.database.services import ArticleService
from app.feeds.fetch_articles import fetch_articles
from app.utils.concurrency import run_concurrently_with_limit
from app.providers.news_provider import ArticleMetadata
from app.clusterer.cluster import cluster


async def process(
    extractor: Extractor,
    providers: list[str] | None,
    embeddings: Embeddings,
):
    start_time = time.perf_counter()
    article_metadatas = await fetch_articles(providers)

    with database_session() as uow:
        article_urls = [article_metadata.link for article_metadata in article_metadatas]
        existing_urls = uow.articles.get_existing_urls(article_urls)

        new_article_metadatas = [
            article_metadata
            for article_metadata in article_metadatas
            if article_metadata.link not in existing_urls
        ]

        logging.info(f"Found {len(new_article_metadatas)} new articles")

        tasks = [
            extract_article(article_metadata.link, extractor)
            for article_metadata in new_article_metadatas
        ]
        results, _ = await run_concurrently_with_limit(tasks, limit=3)
        extracted_articles: list[ExtractedArticle] = [
            result for result in results if isinstance(result, ExtractedArticle)
        ]

        # join metadata and extracted values, to prevent mismatches in case of errors
        new_article_metadatas, extracted_articles = join_articles(
            new_article_metadatas, extracted_articles
        )

        # TODO: errors
        summaries = await generate_summaries(new_article_metadatas, extracted_articles)

        articles_embeddings = await generate_embeddings(extracted_articles, summaries, embeddings)

        articles = []
        for article_metadata, extracted_article, summary, embedding in zip(
            new_article_metadatas,
            extracted_articles,
            summaries,
            articles_embeddings,
        ):
            article = Article(
                url=article_metadata.link,
                title=article_metadata.title,
                author=extracted_article.author,
                deck=extracted_article.deck,
                content=extracted_article.content,
                summary=summary,
                published_at=article_metadata.published_at,
                embedding=embedding,
                news_provider_key=article_metadata.provider_key,
            )
            pprint(article)
            articles.append(article)

        # TODO: error handling
        ArticleService.bulk_create_articles(articles, uow)

        # TODO: Save clusters to database
        # labels = cluster(articles_embeddings)

        end_time = time.perf_counter()
        logging.info(
            f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Successfully processed {len(articles)} new articles in {(end_time - start_time):.3f} seconds!"
        )


@retry(
    stop=stop_after_attempt(2),
    wait=wait_exponential(multiplier=1, min=1, max=10),
)
async def extract_article(url: str, extractor: Extractor):
    logging.info(f"Extracting article: {url}")
    try:
        return await extractor.extract_article(url)
    except Exception as e:
        logging.error(f"Error extracting article from {url}: {e}")


def join_articles(
    article_metadatas: list[ArticleMetadata],
    extracted_articles: list[ExtractedArticle],
):
    metadatas = []
    metadata_map = {meta.link: meta for meta in article_metadatas}
    for extracted_article in extracted_articles:
        metadatas.append(metadata_map[extracted_article.url])
    return metadatas, extracted_articles


async def generate_summaries(
    article_metadatas: list[ArticleMetadata], extracted_articles: list[ExtractedArticle]
) -> list[str]:
    model = init_chat_model("gemini-2.0-flash", model_provider="google_genai")
    inputs = []
    for article_metadata, extracted_article in zip(article_metadatas, extracted_articles):
        summary = f"Summary: {article_metadata.summary}" if article_metadata.summary else ""
        deck = f"Deck: {extracted_article.deck}" if extracted_article.deck else ""
        content = f"Content: {extracted_article.content}" if extracted_article.content else ""
        prompt = (
            "You are a professional Slovenian journalist.\n"
            "Write a concise summary (max 3 sentences) of the following article in Slovenian.\n"
            f"Title: {article_metadata.title}\n"
            f"{summary}\n"
            f"{deck}\n"
            f"{content}"
        )
        inputs.append(prompt)
    results = await model.abatch(inputs=inputs)
    return [result.content for result in results]


async def generate_embeddings(
    articles: list[ExtractedArticle], summaries: list[str], embeddings: Embeddings
) -> list[list[float]]:
    documents = [f"{article.title}\n{summary}" for article, summary in zip(articles, summaries)]
    article_embeddings = await embeddings.aembed_documents(documents)
    return article_embeddings

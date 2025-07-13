import asyncio
import time
import logging
from langchain_core.embeddings import Embeddings
from pprint import pprint
from tenacity import retry, stop_after_attempt, wait_exponential

from app.extractor.extractor import Extractor, ExtractedArticle
from app.database.database import Database, Article
from app.feeds.fetch_articles import fetch_articles
from app.utils.concurrency import run_concurrently_with_limit
from app.providers.news_provider import ArticleMetadata


async def process(
    extractor: Extractor,
    db: Database,
    providers: list[str] | None,
    embeddings: Embeddings,
):
    start_time = time.perf_counter()
    article_metadatas = await fetch_articles(providers)

    article_urls = [article_metadata.link for article_metadata in article_metadatas]
    existing_urls = db.get_articls_by_urls(article_urls)

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
    results, errors = await run_concurrently_with_limit(tasks, limit=3)
    extracted_articles: list[ExtractedArticle] = [
        result for result in results if isinstance(result, ExtractedArticle)
    ]

    # TODO: errors
    articles_embeddings = generate_embeddings(extracted_articles, embeddings)

    articles = join_articles(
        new_article_metadatas, extracted_articles, articles_embeddings
    )

    # TODO: error handling
    db.bulk_insert_articles(articles)

    end_time = time.perf_counter()
    logging.info(
        f"Successfully processed {len(articles)} new articles in  {(end_time - start_time):.3f} seconds!"
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


def generate_embeddings(
    articles: list[ExtractedArticle], embeddings: Embeddings
) -> list[list[float]]:
    decks = [article.deck for article in articles]
    article_embeddings = embeddings.embed_documents(decks)
    return article_embeddings


def join_articles(
    article_metadatas: list[ArticleMetadata],
    extracted_articles: list[ExtractedArticle],
    articles_embeddings: list[list[float]],
):
    articles = []
    metadata_map = {meta.link: meta for meta in article_metadatas}
    for extracted_article, embedding in zip(extracted_articles, articles_embeddings):
        article_metadata = metadata_map[extracted_article.url]
        article = Article(
            url=article_metadata.link,
            title=article_metadata.title,
            author=extracted_article.author,
            deck=extracted_article.deck,
            content=extracted_article.content,
            published_at=article_metadata.published_at,
            embedding=embedding,
            news_provider_key=article_metadata.provider_key,
        )
        pprint(article)
        articles.append(article)
    return articles

import asyncio
import dotenv

from app.extractor.extractor import Extractor, ExtractedArticle
from app.extractor.llm_extractor import LlmExtractor
from app.extractor.readability_extractor import ReadabilityExtractor
from app.database.database import Database, Article
from app.database.seed_news_providers import seed_new_providers

from app.feeds.fetch_articles import fetch_articles
import argparse
import logging
from pprint import pprint
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_core.embeddings import Embeddings


async def main():
    dotenv.load_dotenv()
    logging.basicConfig(level=logging.INFO)

    parser = argparse.ArgumentParser(description="Article Scraper")

    parser.add_argument(
        "--providers",
        type=lambda s: s.split(","),
        help="Comma-separated list of providers (e.g., provider1,provider2,provider3)",
    )

    args = parser.parse_args()

    providers: str | None = args.providers

    extractor: Extractor = ReadabilityExtractor()
    db = Database()
    embeddings = GoogleGenerativeAIEmbeddings(model="models/text-embedding-004")

    # TODO: move somewhere else?
    seed_new_providers(db)

    await process(
        extractor=extractor,
        db=db,
        providers=providers,
        embeddings=embeddings,
    )

    db.close()


async def process(
    extractor: Extractor,
    db: Database,
    providers: list[str] | None,
    embeddings: Embeddings,
):
    article_metadatas = await fetch_articles(providers)

    article_urls = [article_metadata.link for article_metadata in article_metadatas]
    existing_urls = db.get_articls_by_urls(article_urls)

    new_article_metadatas = [
        article_metadata
        for article_metadata in article_metadatas
        if article_metadata.link not in existing_urls
    ]

    logging.info(f"Found {len(new_article_metadatas)} new articles")

    # extractor: Extractor = LlmExtractor()

    # TODO: separate checking if article exists in DB and processing the article
    # TODO: add concurrency,
    # retries, timeout, error handling
    extracted_articles: list[ExtractedArticle] = []
    for article_metadata in new_article_metadatas:
        extracted_article = await extract_article(article_metadata.link, extractor)
        if extracted_article:
            extracted_articles.append(extracted_article)

    # TODO: errors
    articles_embeddings = await generate_embeddings(extracted_articles, embeddings)

    articles = []
    for article_metadata, extracted_article, embedding in zip(
        new_article_metadatas, extracted_articles, articles_embeddings
    ):
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

    # TODO: error handling
    db.bulk_insert_articles(articles)
    logging.info("Successfully processed new articles!")


async def extract_article(url: str, extractor: Extractor):
    logging.info(f"Extracting article: {url}")
    # TODO: better error handling
    # TODO: this is deprecated nonsense
    try:
        content = await extractor.extract_article(url)
        return content
    except Exception as e:
        logging.error(f"Error extracting article from {url}: {e}")


async def generate_embeddings(
    articles: list[ExtractedArticle], embeddings: Embeddings
) -> list[list[float]]:
    decks = [article.deck for article in articles]
    article_embeddings = embeddings.embed_documents(decks)
    return article_embeddings


if __name__ == "__main__":
    asyncio.run(main())

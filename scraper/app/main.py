import asyncio
import dotenv

from app.extractor.extractor import Extractor
from app.extractor.llm_extractor import LlmExtractor
from app.extractor.readability_extractor import ReadabilityExtractor
from app.database import Database

from app.feeds.fetch_articles import fetch_articles
import argparse
import logging
from datetime import datetime
from pprint import pprint
from langchain_google_genai import GoogleGenerativeAIEmbeddings


async def main():
    dotenv.load_dotenv()

    parser = argparse.ArgumentParser(description="Article Scraper")

    parser.add_argument(
        "--providers",
        type=lambda s: s.split(","),
        help="Comma-separated list of providers (e.g., provider1,provider2,provider3)",
    )

    args = parser.parse_args()
    providers = args.providers

    article_urls = await fetch_articles(providers)
    # TODO: check if we can use this: https://newspaper.readthedocs.io/en/latest/
    # or https://github.com/alan-turing-institute/ReadabiliPy (port of @mozilla/readability npm package) + html to markdown to get rid of divs
    # after that we can use some sort of Markdown react component to render the markdown in the web app
    # extractor: Extractor = LlmExtractor()
    extractor: Extractor = ReadabilityExtractor()
    db = Database()

    # TODO: add concurrency, retries, timeout, error handling
    articles = []
    for url in article_urls:
        # if db.items_exists(url):
        #     print(f"Article already exists in DB: {url}")
        #     continue
        article = await process_article(url, extractor)
        if article:
            articles.append(article)

    # await generate_embeddings(articles)  # TODO: errors
    db.bulk_put(articles)


async def process_article(url: str, extractor: Extractor):
    print(f"Processing article: {url}")
    # TODO: better error handling
    try:
        content = await extractor.extract_article(url)
        dict_content = content.model_dump()
        dict_content["url"] = url
        dict_content["created_at"] = int(datetime.now().timestamp())
        pprint(dict_content)
        return dict_content
    except Exception as e:
        logging.error(f"Error extracting article from {url}: {e}")


async def generate_embeddings(articles):
    decks = [article["deck"] for article in articles]
    embeddings = GoogleGenerativeAIEmbeddings(model="models/text-embedding-004")
    article_embeddings = await embeddings.embed_documents(decks)

    for vector, article in zip(article_embeddings, articles):
        article["embedding"] = vector


if __name__ == "__main__":
    asyncio.run(main())

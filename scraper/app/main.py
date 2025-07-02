import asyncio
import dotenv

from app.extractor.extract_article import Extractor
from app.database import Database

from app.feeds.fetch_articles import fetch_articles
import argparse
import logging
from datetime import datetime
from pprint import pprint


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
    # or https://github.com/alan-turing-institute/ReadabiliPy (port of @mozilla/readability npm package)
    extractor = Extractor()
    db = Database()

    # TODO: add concurrency, retries, timeout, error handling
    for url in article_urls:
        if db.items_exists(url):
            print(f"Article already exists in DB: {url}")
            continue
        print(f"Processing article: {url}")
        # TODO: better error handling
        try:
            content = await extractor.extract_article(url)
            dict_content = content.model_dump()
            dict_content["url"] = url
            dict_content["created_at"] = int(datetime.now().timestamp())
            pprint(dict_content)
            db.put_item(dict_content)
        except Exception as e:
            logging.error(f"Error extracting article from {url}: {e}")


if __name__ == "__main__":
    asyncio.run(main())

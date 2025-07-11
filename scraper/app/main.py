import asyncio
import dotenv
import logging
import argparse
from langchain_google_genai import GoogleGenerativeAIEmbeddings

from app.extractor.extractor import Extractor
from app.extractor.readability_extractor import ReadabilityExtractor
from app.database.database import Database
from app.database.seed_news_providers import seed_new_providers
from app.process import process


async def main() -> None:
    dotenv.load_dotenv()
    logging.basicConfig(level=logging.INFO)

    return

    parser = argparse.ArgumentParser(description="Article Scraper")

    parser.add_argument(
        "--providers",
        type=lambda s: s.split(","),
        help="Comma-separated list of providers (e.g., provider1,provider2,provider3)",
    )

    args = parser.parse_args()

    providers: list[str] | None = args.providers

    # TODO: move somewhere else?
    seed_new_providers()

    # TODO: implement recovering from a checkpoint timestamp
    # in case the scraper crashes, so we don't miss any articles

    try:
        while True:
            await run(providers)
            await asyncio.sleep(10 * 60)  # 10 minutes
    except KeyboardInterrupt:
        logging.info("Shutting down...")


async def run(providers: list[str] | None = None) -> None:
    extractor: Extractor = ReadabilityExtractor()
    embeddings = GoogleGenerativeAIEmbeddings(model="models/text-embedding-004")
    db = Database()

    await process(
        extractor=extractor,
        db=db,
        providers=providers,
        embeddings=embeddings,
    )

    db.close()


if __name__ == "__main__":
    asyncio.run(main())

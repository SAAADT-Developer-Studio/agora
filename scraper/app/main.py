import asyncio
import dotenv
import logging
import argparse
from langchain.chat_models import init_chat_model
from langchain_google_genai import GoogleGenerativeAIEmbeddings

from app.database.services import NewsProviderService
from app.pipeline import process
from app.providers.providers import PROVIDERS
from app import config

import httpx


async def main() -> None:
    dotenv.load_dotenv()
    logging.basicConfig(level=logging.INFO)

    parser = argparse.ArgumentParser(description="Article Scraper")

    parser.add_argument(
        "--providers",
        type=lambda s: s.split(","),
        help="Comma-separated list of providers (e.g., provider1,provider2,provider3)",
    )

    args = parser.parse_args()

    providers: list[str] | None = args.providers

    NewsProviderService.sync_providers(PROVIDERS)

    # TODO: implement recovering from a checkpoint timestamp
    # in case the scraper crashes, so we don't miss any articles

    # Keep track of background cache population tasks
    background_tasks = set()

    try:
        while True:
            cache_task = await run(providers)
            # Keep reference to prevent task from being garbage collected
            background_tasks.add(cache_task)
            cache_task.add_done_callback(background_tasks.discard)

            await asyncio.sleep(10 * 60)  # 10 minutes
    except KeyboardInterrupt:
        logging.info("Shutting down...")


async def run(providers: list[str] | None = None) -> asyncio.Task:
    embeddings = GoogleGenerativeAIEmbeddings(model="models/text-embedding-004")
    analysis_model = init_chat_model("gemini-2.0-flash", model_provider="google_genai")

    await process(
        providers=providers,
        embeddings=embeddings,
        analysis_model=analysis_model,
    )

    # Populate cache after processing - non-blocking with error handling
    return asyncio.create_task(populate_cache())


async def populate_cache() -> None:
    if config.APP_ENV == "development":
        logging.info("Skipping cache population in development environment")
        return
    try:
        async with httpx.AsyncClient(timeout=90.0) as client:
            response = await client.post("https://vidik.si/api/populate-cache")
            response.raise_for_status()
            logging.info("Successfully populated cache")
    except httpx.TimeoutException:
        logging.error("Timeout while populating cache")
    except httpx.HTTPStatusError as e:
        logging.error(f"HTTP error while populating cache: {e.response.status_code}")
    except Exception as e:
        logging.error(f"Unexpected error while populating cache: {e}")


if __name__ == "__main__":
    asyncio.run(main())

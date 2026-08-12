import asyncio
import dotenv
import logging
import argparse
from langchain_openai import OpenAIEmbeddings

from app.database.services import NewsProviderService
from app.pipeline import process
from app.providers.providers import PROVIDERS
from app.openrouter import create_openrouter_chat_model


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

    try:
        while True:
            await run(providers)
            await asyncio.sleep(10 * 60)  # 10 minutes
    except KeyboardInterrupt:
        logging.info("Shutting down...")


async def run(providers: list[str] | None = None) -> None:
    # https://docs.langchain.com/oss/python/integrations/text_embedding/cloudflare_workersai
    # from langchain_cloudflare.embeddings import (
    #     CloudflareWorkersAIEmbeddings,
    # )
    embeddings = OpenAIEmbeddings(
        model="text-embedding-3-small",
        dimensions=768,
    )
    analysis_model = create_openrouter_chat_model()

    await process(
        providers=providers,
        embeddings=embeddings,
        analysis_model=analysis_model,
    )


if __name__ == "__main__":
    asyncio.run(main())

import argparse
import asyncio
import logging
import os
from pathlib import Path

from dotenv import load_dotenv


async def main(argv: list[str] | None = None):
    parser = argparse.ArgumentParser(description="Run clustering on the configured database")
    parser.add_argument("--dev", action="store_true", help="Use DEV_DATABASE_URL from the repo-root .env")
    parser.add_argument("--bootstrap", action="store_true", help="Cluster all existing articles from scratch, without external API calls")
    parser.add_argument("--days", type=int, help="With --bootstrap, only cluster articles published in the last N days")
    args = parser.parse_args(argv)
    if args.days is not None and (args.days < 1 or not args.bootstrap):
        parser.error("--days requires --bootstrap and must be positive")
    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
    if args.dev:
        target = os.getenv("DEV_DATABASE_URL")
        if not target:
            parser.error("Set DEV_DATABASE_URL in the repo-root .env")
        os.environ["DATABASE_URL"] = target
    # Select the connection before database.schema initializes its engine.
    from database.unit_of_work import database_session
    from app.clusterer.run_clustering import bootstrap_cluster_run, run_clustering

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.info("Clustering using %s", "DEV_DATABASE_URL" if args.dev else "DATABASE_URL")
    with database_session() as uow:
        if args.bootstrap:
            await bootstrap_cluster_run(uow, article_limit=None, enrich_images=False, days=args.days)
        else:
            from app.openrouter import create_openrouter_chat_model
            await run_clustering(uow, create_openrouter_chat_model())
    logging.info("Clustering committed")


if __name__ == "__main__":
    asyncio.run(main())

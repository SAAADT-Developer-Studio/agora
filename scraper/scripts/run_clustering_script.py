import asyncio

from langchain.chat_models import init_chat_model
from app.database.unit_of_work import database_session
from app.clusterer.run_clustering import run_clustering
from app import config


async def main():
    model = init_chat_model(
        "deepseek/deepseek-v4-flash",
        model_provider="openai",
        base_url=config.OPENROUTER_BASE_URL,
        api_key=config.OPENROUTER_API_KEY,
    )
    with database_session() as uow:
        await run_clustering(uow, model)


if __name__ == "__main__":
    asyncio.run(main())

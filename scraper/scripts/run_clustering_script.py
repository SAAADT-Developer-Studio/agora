import asyncio

from app.database.unit_of_work import database_session
from app.clusterer.run_clustering import run_clustering
from app.openrouter import create_openrouter_chat_model


async def main():
    model = create_openrouter_chat_model()
    with database_session() as uow:
        await run_clustering(uow, model)


if __name__ == "__main__":
    asyncio.run(main())

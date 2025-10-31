import asyncio

from app.database.unit_of_work import database_session
from app.clusterer.run_clustering import run_clustering


async def main():
    with database_session() as uow:
        await run_clustering(uow)


if __name__ == "__main__":
    asyncio.run(main())

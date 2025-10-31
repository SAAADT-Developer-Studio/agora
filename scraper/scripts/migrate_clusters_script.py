import asyncio

from app.database.unit_of_work import database_session
from app.clusterer.run_clustering import migrate_clusters


async def main():
    with database_session() as uow:
        await migrate_clusters(uow)


if __name__ == "__main__":
    asyncio.run(main())

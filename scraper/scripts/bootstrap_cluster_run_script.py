import asyncio

from app.database.unit_of_work import database_session
from app.clusterer.run_clustering import bootstrap_cluster_run


async def main():
    with database_session() as uow:
        await bootstrap_cluster_run(uow)


if __name__ == "__main__":
    asyncio.run(main())

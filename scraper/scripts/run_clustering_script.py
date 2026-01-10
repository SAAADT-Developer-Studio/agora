import asyncio

from langchain.chat_models import init_chat_model
from app.database.unit_of_work import database_session
from app.clusterer.run_clustering import run_clustering


async def main():
    model = init_chat_model("gemini-2.0-flash", model_provider="google_genai")
    with database_session() as uow:
        await run_clustering(uow, model)


if __name__ == "__main__":
    asyncio.run(main())

import asyncio
import dotenv

from extractor import extract_article
from models import Article
from database import connect_db
from sqlmodel import Session


async def main():
    dotenv.load_dotenv()
    engine = connect_db()

    article = await extract_article(
        "https://www.24ur.com/novice/gospodarstvo/ameriska-centralna-banka-ohranila-kljucno-obrestno-mero.html"
    )
    exit()
    with Session(engine) as session:
        session.add(
            Article(
                title=article.title,
                author=article.author,
                summary=article.summary,
                content=article.content,
                num_comments=article.num_comments,
            )
        )
        session.commit()


if __name__ == "__main__":
    asyncio.run(main())

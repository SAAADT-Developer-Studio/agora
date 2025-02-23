import asyncio
import dotenv

from app.extractor import extract_article
from app.models import Article
from app.database import connect_db
from sqlmodel import Session
from app.fetch_urls import fetch_articles

async def main():
    dotenv.load_dotenv()
    engine = connect_db()

    articles = await fetch_articles()
    exit()
    article = await extract_article(
        "https://www.24ur.com/novice/gospodarstvo/ameriska-centralna-banka-ohranila-kljucno-obrestno-mero.html"
    )
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

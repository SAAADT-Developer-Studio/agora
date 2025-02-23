from datetime import datetime
from app.utils import is_recent
from app.extractor import extract

BASE_URL = "https://svet24.si"

async def fetch_articles():
    url=f"{BASE_URL}/najnovejse"
    schema = {
        "name": "Article urls",
        "baseSelector": "a",
        "fields": [
            {
                "name": "article_path",
                "type": "attribute",
                "attribute": "href"
            },
            {
                "name": "date",
                "type": "regex",
                "pattern": r"(\d{2}:\d{2})",
            },
        ]
    }
    data = await extract(url, schema)
    urls = []
    for article in data:
        path = article["article_path"]
        if not path.startswith("/clanek/"):
            continue
        date = datetime.now()
        if "date" in article:
            hour, minute = map(int, article["date"].split(":"))
            date = date.replace(hour=hour, minute=minute)
        if is_recent(date):
            article_path = article["article_path"]
            urls.append(f"{BASE_URL}{article_path}")
            print(path, date)
    return urls
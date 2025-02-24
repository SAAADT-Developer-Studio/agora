from datetime import datetime
from app.utils import is_recent
from app.extractor import extract

BASE_URL = "https://ljnovice.si"

async def fetch_articles():
    url=f"{BASE_URL}/news-sitemap.xml"
    schema = {
        "name": "Article urls",
        "baseSelector": "tr",
        "fields": [
            {
                "name": "article_path",
                "selector": "a",
                "type": "attribute",
                "attribute": "href"
            },
            {
                "name": "date",
                "selector": "td:nth-child(4)",
                "type": "text",
            },
        ]
    }
    data = await extract(url, schema)
    urls = []
    for article in data:
        date = datetime.fromisoformat(article["date"])
        if is_recent(date):
            article_url = article["article_path"]
            urls.append(article_url)
    return urls
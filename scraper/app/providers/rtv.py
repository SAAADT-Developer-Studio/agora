from datetime import datetime
from app.utils import is_recent
from app.extractor import extract

BASE_URL = "https://www.rtvslo.si"

async def fetch_articles():
    url=f"{BASE_URL}/zadnje?&p=0"
    schema = {
        "name": "Article urls",
        "baseSelector": "div.article-archive-item",
        "fields": [
            {
                "name": "article_path",
                "selector": "a.image-link",
                "type": "attribute",
                "attribute": "href"
            },
            {
                "name": "date",
                "type": "attribute",
                "attribute": "date-is"
            },
        ]
    }
    data = await extract(url, schema)
    urls = []
    for article in data:
        date = datetime.strptime(article["date"], '%d.%m.%Y %H:%M')
        if is_recent(date):
            article_path = article["article_path"]
            urls.append(f"{BASE_URL}{article_path}")
    return urls
from datetime import datetime
from app.utils import is_recent
from app.extractor import extract

BASE_URL = "https://primorske.svet24.si"
# TODO: handle edge case of articles that are not in the current year

async def fetch_articles():
    current_year = datetime.now().year
    url=f"{BASE_URL}/{current_year}"
    schema = {
        "name": "Article urls",
        "baseSelector": ".article-medium",
        "fields": [
            {
                "name": "article_path",
                "selector": "a.image-link",
                "type": "attribute",
                "attribute": "href"
            },
            {
                "name": "date",
                "selector": ".article-published",
                "type": "attribute",
                "attribute": "datetime",
            },
        ]
    }
    data = await extract(url, schema)
    urls = []
    for article in data:
        date = datetime.strptime(article["date"], "%Y-%m-%dT%H:%M:%S")
        if is_recent(date):
            article_path = article["article_path"]
            urls.append(f"{BASE_URL}{article_path}")
    return urls
from datetime import datetime
from app.utils import is_recent
from app.extractor import extract

BASE_URL = "https://siol.net"

async def fetch_articles():
    url=f"{BASE_URL}/pregled-dneva"
    schema = {
        "name": "Article urls",
        "baseSelector": ".timeline_page__article",
        "fields": [
            {
                "name": "article_path",
                "selector": "a.card__link",
                "type": "attribute",
                "attribute": "href"
            },
            {
                "name": "date",
                "selector": "p.timeline_page__article_wrap_info_time",
                "type": "text",
            },
        ]
    }
    data = await extract(url, schema)
    urls = []
    for article in data:
        date = datetime.now()
        hour, minute = map(int, article["date"].split("."))
        date = date.replace(hour=hour, minute=minute)
        if is_recent(date):
            article_path = article["article_path"]
            urls.append(f"{BASE_URL}{article_path}")
    return urls
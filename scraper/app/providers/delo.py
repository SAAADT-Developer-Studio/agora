from datetime import datetime
from app.utils import is_recent
from app.extractor import extract

BASE_URL = "https://www.delo.si"

async def fetch_articles():
    url=f"{BASE_URL}/arhiv"
    schema = {
        "name": "Article urls",
        "baseSelector": "div.archive_teaser",
        "fields": [
            {
                "name": "article_path",
                "selector": "a.teaser_link",
                "type": "attribute",
                "attribute": "href"
            },
            {
                "name": "date",
                "selector": "span.datetime",
                "type": "text",
            },
        ]
    }
    data = await extract(url, schema)
    urls = []
    for article in data:
        date = datetime.strptime(article["date"], '%d. %m. %Y| %H:%M')
        if is_recent(date):
            article_path = article["article_path"]
            urls.append(f"{BASE_URL}{article_path}")
    return urls
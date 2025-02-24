from datetime import datetime
from app.utils import is_recent
from app.extractor import extract

BASE_URL = "https://www.mladina.si"

async def fetch_articles():
    url=f"{BASE_URL}"
    schema = {
        "name": "Article urls",
        "baseSelector": ".articles .item",
        "fields": [
            {
                "name": "article_path",
                "selector": ".image a",
                "type": "attribute",
                "attribute": "href"
            },
            {
                "name": "date",
                "selector": "[name=\"info\"]",
                "type": "attribute",
                "attribute": "data-c-date",
            },
        ]
    }
    data = await extract(url, schema)
    urls = []
    for article in data:
        date = datetime.strptime(article["date"], "%d. %m. %Y")
        if "article_path" not in article or "date" not in article:
            continue
        article_url = f"{BASE_URL}{article["article_path"]}"
        if date.date() == datetime.now().date():
            urls.append(article_url)
    return urls
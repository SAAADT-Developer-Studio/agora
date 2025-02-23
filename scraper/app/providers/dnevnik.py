
from app.extractor import extract

BASE_URL = "https://www.dnevnik.si"

async def fetch_articles():
    url=f"{BASE_URL}/najnovejse"
    schema = {
        "name": "Article urls",
        "baseSelector": ".se-card--link",
        "fields": [
            {
                "name": "article_path",
                "type": "attribute",
                "attribute": "href"
            },
        ]
    }
    data = await extract(url, schema)
    urls = []
    for article in data[:15]:
        article_path = article["article_path"]
        urls.append(f"{BASE_URL}{article_path}")
    return urls
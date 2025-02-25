from datetime import datetime
from app.utils import is_recent
from app.extractor import extract

BASE_URL = "https://slo-tech.com"

async def fetch_articles():
    url=f"{BASE_URL}/novice/arhiv"
    schema = {
        "name": "Article urls",
        "baseSelector": "article",
        "fields": [
            {
                "name": "article_path",
                "selector": "meta[itemprop=mainEntityOfPage]",
                "type": "attribute",
                "attribute": "itemid"
            },
            {
                "name": "date",
                "selector": "meta[itemprop=dateModified]",
                "type": "attribute",
                "attribute": "content"
            },
        ]
    }
    data = await extract(url, schema)
    urls = []
    for article in data:
        date = datetime.fromisoformat(article["date"])
        if is_recent(date):
            article_path = article["article_path"]
            urls.append(article_path)
    return urls
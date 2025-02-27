

import xmltodict
import httpx
from datetime import datetime
from app.utils import is_recent

BASE_URL = "https://www.sta.si"

async def fetch_articles():
    url = f"{BASE_URL}/rss-0"
    async with httpx.AsyncClient() as client:
        response = await client.get(url)
        document = xmltodict.parse(response.text)
        articles = document["rss"]["channel"]["item"]
        urls = []
        for article in articles:
            date = datetime.strptime(article["pubDate"], "%a, %d %b %Y %H:%M:%S %z")
            article_url = article["link"]
            if is_recent(date):
                urls.append(article_url)
        return urls
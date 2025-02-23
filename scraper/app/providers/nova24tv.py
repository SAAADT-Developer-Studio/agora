from datetime import datetime
from app.utils import is_recent
from app.extractor import extract
import xmltodict
import httpx
import asyncio

BASE_URL = "https://nova24tv.si"
# category sitemap https://nova24tv.si/category-sitemap.xml

async def fetch_articles():
    url = f"{BASE_URL}/post-sitemap.xml"
    async with httpx.AsyncClient() as client:
        client.headers["User-Agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3"
        response = await client.get(url)
        document = xmltodict.parse(response.text)
        articles = document["urlset"]["url"]
        urls = []
        for article in articles:
            article_url = article["loc"]
            last_mod = datetime.fromisoformat(article["lastmod"])
            if is_recent(last_mod):
                urls.append(article_url)
        return urls
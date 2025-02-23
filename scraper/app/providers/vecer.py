from datetime import datetime, timedelta
from app.utils import is_recent
import httpx
import asyncio

BASE_URL = "https://vecer.com"

async def fetch_articles():
    start_date = (datetime.now() - timedelta(days=1)).date()
    end_date = datetime.now().date()
    n_pages = 50
    url = f"{BASE_URL}/rubrika/danes-objavljeno/1/{n_pages}/{start_date} 00:00:00/{end_date} 23:59:59"
    async with httpx.AsyncClient() as client:
        response = await client.get(url)
        articles = response.json()
        urls = []
        for article in articles:
            article_url = f"{BASE_URL}{article["url"]}"
            date = datetime.fromisoformat(article["published"])
            if is_recent(date):
                urls.append(article_url)
        return urls
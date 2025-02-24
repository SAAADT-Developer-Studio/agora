import xmltodict
import httpx
import asyncio
from datetime import datetime
from app.utils import is_recent
import itertools

BASE_URL = "https://maribor24.si"

async def fetch_page_articles(url: str) -> list[str]:
    async with httpx.AsyncClient() as client:
        response = await client.get(url)
        document = xmltodict.parse(response.text)
        articles = document["urlset"]["url"]
        urls = []
        for article in articles:
            url = article["loc"]
            last_mod = datetime.fromisoformat(article["lastmod"])
            if is_recent(last_mod):
                urls.append(url)
        return urls


async def fetch_articles():
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{BASE_URL}/sitemap.xml")
        document = xmltodict.parse(response.text)
        sitemaps = [
            sitemap["loc"]
            for sitemap in document["sitemapindex"]["sitemap"]
            if sitemap["loc"].startswith("https://maribor24.si/sitemap-articles")
        ]

        second_last_page, last_page = sitemaps[-2:]
        results = await asyncio.gather(
            fetch_page_articles(last_page),
            fetch_page_articles(second_last_page),
        )
        urls = list(itertools.chain(*results))
        return urls

import xmltodict
import httpx
import asyncio
from datetime import datetime, timedelta
import itertools
from app import config

async def fetch_page_articles(url: str) -> list[str]:
    async with httpx.AsyncClient() as client:
        response = await client.get(url)
        document = xmltodict.parse(response.text)
        articles = document["urlset"]["url"]
        urls = []
        for article in articles:
            url = article["loc"]
            last_mod = datetime.fromisoformat(article["lastmod"])
            if last_mod > datetime.now(last_mod.tzinfo) - timedelta(**config.TIME_WINDOW):
                urls.append(url)
        return urls



async def fetch_articles():
    async with httpx.AsyncClient() as client:
        response = await client.get("https://www.24ur.com/sitemaps/sites/1")
        document = xmltodict.parse(response.text)
        second_last_page, last_page = document["sitemapindex"]["sitemap"][-2:]

        results = await asyncio.gather(
            fetch_page_articles(last_page["loc"]),
            fetch_page_articles(second_last_page["loc"]),
        )
        urls = list(itertools.chain(*results))
        print(urls)
        return urls

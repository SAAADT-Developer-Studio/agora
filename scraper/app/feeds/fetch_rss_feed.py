import httpx
import feedparser
from pprint import pprint


async def fetch_rss_feed(url: str):
    async with httpx.AsyncClient() as client:
        client.follow_redirects = True
        response = await client.get(url)
        feed = feedparser.parse(response.text)
        return feed["entries"]

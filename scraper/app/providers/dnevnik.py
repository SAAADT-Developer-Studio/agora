from app.utils import is_recent
from app.feeds.fetch_rss_feed import fetch_rss_feed
from datetime import datetime

BASE_URL = "https://www.dnevnik.si/rss.xml"


async def fetch_articles():
    articles = await fetch_rss_feed(BASE_URL)
    urls = []
    for article in articles:
        date_format = "%Y-%m-%d %H:%M:%S"
        date = datetime.strptime(article["published"], date_format)
        if is_recent(date):
            urls.append(article["link"])
    return urls

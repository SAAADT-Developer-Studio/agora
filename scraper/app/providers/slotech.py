from app.utils import is_recent
from app.feeds.fetch_rss_feed import fetch_rss_feed
from datetime import datetime

BASE_URL = "http://feeds.st.si/ST-novice"


async def fetch_articles():
    articles = await fetch_rss_feed(BASE_URL)
    urls = []
    for article in articles:
        date_format = "%a, %d %b %Y %H:%M:%S %z"
        date = datetime.strptime(article["published"], date_format)
        if is_recent(date):
            urls.append(article["link"])
    return urls

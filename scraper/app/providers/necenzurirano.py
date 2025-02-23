from datetime import datetime
from app.utils import is_recent
from app.extractor import extract
import re

BASE_URL = "https://necenzurirano.si"

async def fetch_newst_articles():
    url=f"{BASE_URL}"
    schema = {
        "name": "Article urls",
        "baseSelector": "a:has(article)",
        "fields": [
            {
                "name": "article_path",
                "type": "attribute",
                "attribute": "href"
            },
            {
                "name": "article",
                "selector": "article",
                "type": "text",
            },
        ]
    }
    return await extract(url, schema)

async def fetch_old_articles():
    url=f"{BASE_URL}"
    schema = {
        "name": "Article urls",
        "baseSelector": "article a",
        "fields": [
            {
                "name": "article_path",
                "type": "attribute",
                "attribute": "href"
            },
            {
                "name": "article",
                "type": "text",
            },
        ]
    }
    return await extract(url, schema)

async def parse_articles(data):
    urls = []
    for article in data:
        article_content = article["article"]
        article_url = f"{BASE_URL}/{article["article_path"]}"
        date_pattern = r'(\d+)\.\s*(januar|februar|marec|april|maj|junij|julij|avgust|september|oktober|november|december)\s*(\d{4})'
        match = re.search(date_pattern, article_content)
        if match:
            day, month_name, year = match.groups()
            month_dict = {'januar': 1, 'februar': 2, 'marec': 3, 'april': 4, 'maj': 5, 'junij': 6,
                          'julij': 7, 'avgust': 8, 'september': 9, 'oktober': 10, 'november': 11, 'december': 12}
            date = datetime(int(year), month_dict[month_name], int(day))
            if date.date() == datetime.now().date():
                urls.append(article_url)
    return urls

async def fetch_articles():
    urls = await parse_articles(await fetch_newst_articles())
    urls.extend(await parse_articles(await fetch_old_articles()))
    return urls
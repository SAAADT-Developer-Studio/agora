import xmltodict
import httpx

BASE_URL = "https://www.planet-tv.si"

async def fetch_articles():
    url = f"{BASE_URL}/rss"
    async with httpx.AsyncClient() as client:
        # client.headers["User-Agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3"
        response = await client.get(url)
        document = xmltodict.parse(response.text)
        articles = document["rss"]["channel"]["item"]
        urls = []
        for article in articles[-10:]:
            article_url = f"{BASE_URL}{article["link"]["@href"]}"
            urls.append(article_url)
        return urls
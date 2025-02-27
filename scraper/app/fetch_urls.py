from app.providers import (
    _24ur,
    rtv,
    delo,
    siol,
    nova24tv,
    necenzurirano,
    dnevnik,
    svet24,
    vecer,
    mladina,
    primorskenovice,
    ljubljanskenovice,
    maribor24,
    planettv,
    slotech,
    reporter,
    n1info,
    zurnal24,
    slovenskenovice,
    sta,
)
import asyncio
import logging
from tenacity import retry, stop_after_attempt, wait_exponential

# TODO: move these to config.py

CONCURRENCY_LIMIT = 5
RETRY_ATTEMPTS = 3

semaphore = asyncio.Semaphore(CONCURRENCY_LIMIT)

@retry(stop=stop_after_attempt(RETRY_ATTEMPTS), wait=wait_exponential(multiplier=1, min=1, max=10))
async def fetch(fetch_func: callable, name: str):
    async with semaphore:
        print("fetching", name)
        return await fetch_func()

# TODO: probably refactor and rename these
PROVIDER_RSS_FETCHERS = {
   "24ur": _24ur.fetch_articles,
   "rtv": rtv.fetch_articles,
   "delo": delo.fetch_articles,
   "siol": siol.fetch_articles,
   "nova24tv": nova24tv.fetch_articles,
   "necenzurirano": necenzurirano.fetch_articles,
   "dnevnik": dnevnik.fetch_articles,
   "svet24": svet24.fetch_articles,
   "vecer": vecer.fetch_articles,
   "mladina": mladina.fetch_articles,
   "primorskenovice": primorskenovice.fetch_articles,
   "ljubljanskenovice": ljubljanskenovice.fetch_articles,
   "maribor24": maribor24.fetch_articles,
   "planettv": planettv.fetch_articles,
   "slotech": slotech.fetch_articles,
   "reporter": reporter.fetch_articles,
   "n1info": n1info.fetch_articles,
   "zurnal24": zurnal24.fetch_articles,
   "slovenskenovice": slovenskenovice.fetch_articles,
   "sta": sta.fetch_articles,
}

async def fetch_articles():
    # TODO: dispatch articles to a queue for processing
    # TODO: implement error handling and retries
    # TODO: do the equivalent of p-limit in python to limit concurrency. put `concurreny` in config.py

    tasks = [fetch(fetch_func, name) for name, fetch_func in PROVIDER_RSS_FETCHERS.items()]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    for name, result in zip(PROVIDER_RSS_FETCHERS.keys(), results):
        if isinstance(result, Exception):
            logging.error(f"Failed to fetch from {name}: {result}")
        else:
            logging.info(f"Fetched {len(result)} articles from {name}")

    return results  # TODO: Dispatch articles to a queue for processing

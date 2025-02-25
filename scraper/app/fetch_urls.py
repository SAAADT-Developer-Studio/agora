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
)

async def fetch_articles():
    # TODO: dispatch articles to a queue for processing
    # TODO: implement error handling and retries
    # TODO: do the equivalent of p-limit in python to limit concurrency. put `concurreny` in config.py

    # await _24ur.fetch_articles()
    # await rtv.fetch_articles()
    # await delo.fetch_articles()
    # await siol.fetch_articles()
    # await nova24tv.fetch_articles()
    # await necenzurirano.fetch_articles()
    # await dnevnik.fetch_articles()
    # await svet24.fetch_articles()
    # await vecer.fetch_articles()
    # await mladina.fetch_articles()
    # await primorskenovice.fetch_articles()
    # await ljubljanskenovice.fetch_articles()
    # await maribor24.fetch_articles()
    await planettv.fetch_articles()

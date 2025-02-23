from app.providers import _24ur, rtv, delo, siol, nova24tv, necenzurirano

async def fetch_articles():
  # await _24ur.fetch_articles()
  # await rtv.fetch_articles()
  # await delo.fetch_articles()
  # await siol.fetch_articles()
  # await nova24tv.fetch_articles()
  print(await necenzurirano.fetch_articles())

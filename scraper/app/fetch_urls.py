from app.providers import _24ur, rtv, delo, siol

async def fetch_articles():
  # await _24ur.fetch_articles()
  # await rtv.fetch_articles()
  # await delo.fetch_articles()
  print(await siol.fetch_articles())

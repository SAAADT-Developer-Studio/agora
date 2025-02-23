from app.providers import _24ur, rtv, delo

async def fetch_articles():
  # await _24ur.fetch_articles()
  # await rtv.fetch_articles()
  print(await delo.fetch_articles())

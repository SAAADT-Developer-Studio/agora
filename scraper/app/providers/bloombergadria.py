from scraper.app.providers.news_provider import NewsProvider


class BloombergAdriaProvider(NewsProvider):
    def __init__(self):
        super().__init__(
            name="Bloomberg Adria",
            url="https://si.bloombergadria.com/",
            rss_feeds=[
                "https://si.bloombergadria.com/rss/ekonomija",
                "https://si.bloombergadria.com/rss/posel",
                "https://si.bloombergadria.com/rss/politika",
                "https://si.bloombergadria.com/rss/financni-trgi",
                "https://si.bloombergadria.com/rss/analiza",
            ],
        )

from app.extractor.extractor import Article, Extractor
from pprint import pprint
from readability import parse


class ReadabilityExtractor(Extractor):
    """
    Extractor that uses the mozilla Readability library to extract the main content from an article.
    https://github.com/mozilla/readability
    """

    def __init__(self):
        pass

    async def extract_article(self, url: str) -> Article:
        """
        Extracts the main content from the HTML using Readability.
        """
        html = await self.fetch_article_html(url)
        # documenation https://github.com/mozilla/readability?tab=readme-ov-file#parse
        doc = parse(html)

        print(f"Readability Extractor Result for {url}:")
        print(doc.text_content)

        return Article(
            title=doc.title,
            deck=doc.excerpt,
            content=doc.title,
            author=doc.byline,
            url=url,
            published_at=doc.published_time,
            # image_url=doc.get("lead_image_url", ""),
        )

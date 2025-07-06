from app.extractor.extractor import ExtractedArticle, Extractor
from pprint import pprint
from readability import parse


# TODO: check if we can use this: https://newspaper.readthedocs.io/en/latest/
# or https://github.com/alan-turing-institute/ReadabiliPy (port of @mozilla/readability npm package) + html to markdown to get rid of divs
# after that we can use some sort of Markdown react component to render the markdown in the web app


class ReadabilityExtractor(Extractor):
    """
    Extractor that uses the mozilla Readability library to extract the main content from an article.
    https://github.com/mozilla/readability
    """

    def __init__(self):
        pass

    async def extract_article(self, url: str) -> ExtractedArticle:
        """
        Extracts the main content from the HTML using Readability.
        """
        html = await self.fetch_article_html(url)
        # documenation https://github.com/mozilla/readability?tab=readme-ov-file#parse
        doc = parse(html)

        # TODO: use https://github.com/alan-turing-institute/ReadabiliPy
        # for the main content

        return ExtractedArticle(
            title=doc.title,
            deck=doc.excerpt,
            content=doc.text_content,
            author=doc.byline,
            url=url,
            published_at=doc.published_time,
            # image_url=doc.get("lead_image_url", ""),
        )

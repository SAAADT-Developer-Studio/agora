import os
import os
import getpass
from langchain.chat_models import init_chat_model
from crawl4ai.markdown_generation_strategy import DefaultMarkdownGenerator
from pydantic import BaseModel, Field
from app.extractor.extractor import ExtractedArticle, Extractor

import html2text
from langchain.globals import set_debug


class ArticleStructuredOutput(BaseModel):
    """Class representing an article with its attributes."""

    title: str = Field(description="Title of the article")
    author: str = Field(description="Author of the article")
    deck: str = Field(description="Deck of the article, a summary or brief description")
    content: str = Field(description="Full content of the article")
    num_comments: int = Field(
        description="Number of comments on the article", default=0
    )
    is_error: bool = False


# set_debug(True)


class LlmExtractor(Extractor):
    def __init__(self):
        # if not os.environ.get("OPENAI_API_KEY"):
        #     os.environ["OPENAI_API_KEY"] = getpass.getpass("Enter API key for OpenAI: ")
        # llm = init_chat_model("gpt-4o-mini", model_provider="openai")
        if not os.environ.get("GOOGLE_API_KEY"):
            os.environ["GOOGLE_API_KEY"] = getpass.getpass("Enter API key for Gemini: ")
        self.llm = init_chat_model("gemini-2.0-flash", model_provider="google_genai")
        self.structured_llm = self.llm.with_structured_output(ArticleStructuredOutput)

    async def extract_article(self, url: str) -> ExtractedArticle:
        html = await self.fetch_article_html(url)
        content = self.generate_markdown(html)

        prompt = f"""
            You are an expert data extraction tool. Given the following web article, extract the title, author, the deck, the full content, and the number of comments.
            Present the output in a JSON format that corresponds to the following Python class definition:
            If the article does not contain a deck, create a deck that summarizes the article.
            Anything you write yourself, write in slovenian.
            If anything goes wrong (the input is not valid, the article is blocked by cloudflare, etc.),
            set the is_error field to True, all other fields to an empty string, 0 or whatever empty value is appropriate.
            Here is the markdown of the article:
            {content}
            """
        print(self.llm.get_num_tokens(prompt), url)
        result: ArticleStructuredOutput = self.structured_llm.invoke(prompt)
        return ExtractedArticle(
            title=result.title,
            author=result.author,
            deck=result.deck,
            content=result.content,
            url=url,
            published_at="",  # TODO: extract published date if available
            # num_comments=result.num_comments,
            # is_error=result.is_error,
        )

    def generate_markdown(self, html: str) -> str:
        # return html2text.html2text(html=html)
        markdown_generator = DefaultMarkdownGenerator()
        result = markdown_generator.generate_markdown(cleaned_html=html)
        return result.raw_markdown

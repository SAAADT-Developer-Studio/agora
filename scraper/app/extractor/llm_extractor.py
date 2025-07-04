import os
import os
import getpass
from langchain.chat_models import init_chat_model
from crawl4ai.markdown_generation_strategy import DefaultMarkdownGenerator
import httpx
from scraper.app.extractor.extractor import Article, Extractor

from langchain.globals import set_debug
import html2text

# set_debug(True)


class LlmExtractor(Extractor):
    def __init__(self):
        # if not os.environ.get("OPENAI_API_KEY"):
        #     os.environ["OPENAI_API_KEY"] = getpass.getpass("Enter API key for OpenAI: ")
        # llm = init_chat_model("gpt-4o-mini", model_provider="openai")
        if not os.environ.get("GOOGLE_API_KEY"):
            os.environ["GOOGLE_API_KEY"] = getpass.getpass("Enter API key for Gemini: ")
        self.llm = init_chat_model("gemini-2.0-flash", model_provider="google_genai")
        self.structured_llm = self.llm.with_structured_output(Article)

    async def extract_article(self, url: str) -> Article:
        async with httpx.AsyncClient() as client:
            client.follow_redirects = True
            # set user agent to avoid cloudflare blocking user agent
            client.headers["User-Agent"] = (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3"
            )

            response = await client.get(url)
            content = self.generate_markdown(response.text)

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
            return self.structured_llm.invoke(prompt)

    def generate_markdown(self, html: str) -> str:
        # return html2text.html2text(html=html)
        markdown_generator = DefaultMarkdownGenerator()
        result = markdown_generator.generate_markdown(cleaned_html=html)
        return result.raw_markdown

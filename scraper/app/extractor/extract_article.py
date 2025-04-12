import os
from pydantic import BaseModel
import os
import getpass
from langchain.chat_models import init_chat_model
import httpx


class Article(BaseModel):
    title: str
    author: str
    deck: str
    content: str
    num_comments: int


class Extractor:
    def __init__(self):
        # if not os.environ.get("OPENAI_API_KEY"):
        #     os.environ["OPENAI_API_KEY"] = getpass.getpass("Enter API key for OpenAI: ")
        # llm = init_chat_model("gpt-4o-mini", model_provider="openai")
        if not os.environ.get("GOOGLE_API_KEY"):
            os.environ["GOOGLE_API_KEY"] = getpass.getpass("Enter API key for Gemini: ")
        llm = init_chat_model("gemini-2.0-flash", model_provider="google_genai")
        self.structured_llm = llm.with_structured_output(Article)

    # TODO: return Article object, not dict
    async def extract_article(self, url: str) -> Article:
        async with httpx.AsyncClient() as client:
            client.follow_redirects = True
            response = await client.get(url)
            content = response.text
            prompt = f"""
                You are an expert data extraction tool. Given the following web article, extract the title, author, the deck, the full content, and the number of comments.
                Present the output in a JSON format that corresponds to the following Python class definition:
                class Article(BaseModel):
                    title: str
                    author: str
                    deck: str
                    content: str
                    num_comments: int
                here is the html of the article:
                {content}
                """
            return self.structured_llm.invoke(prompt)

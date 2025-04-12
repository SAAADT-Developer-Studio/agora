
import os
import json
from pydantic import BaseModel
from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, CacheMode, LLMConfig, JsonCssExtractionStrategy
from crawl4ai.extraction_strategy import LLMExtractionStrategy
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

# TODO: handle potentialy paywalled articles and other possible errors
async def extract_article(article_url: str):
    # 1. Define the LLM extraction strategy
    llm_config = LLMConfig(provider="openai/gpt-4o-mini", api_token=os.getenv('OPENAI_API_KEY'))
    llm_strategy = LLMExtractionStrategy(
        llm_config=llm_config,
        schema=Article.schema_json(), # Or use model_json_schema()
        extraction_type="schema",
        instruction="""
            You are an expert data extraction tool. Given the following web article, extract the title, author, the deck, the full content, and the number of comments.
            Present the output in a JSON format that corresponds to the following Python class definition:
            class Article(BaseModel):
                title: str
                author: str
                deck: str
                content: str
                num_comments: int
        """,
        chunk_token_threshold=1000,
        overlap_rate=0.0,
        apply_chunking=True,
        input_format="html",   # or "html", "fit_markdown"
        extra_args={"temperature": 0.0, "max_tokens": 800}
    )

    # 2. Build the crawler config
    crawl_config = CrawlerRunConfig(
        extraction_strategy=llm_strategy,
        cache_mode=CacheMode.BYPASS,
        exclude_external_links=True,
    )

    # 3. Create a browser config if needed
    browser_cfg = BrowserConfig(headless=True)

    async with AsyncWebCrawler(config=browser_cfg) as crawler:
        # 4. Let's say we want to crawl a single page
        result = await crawler.arun(url=article_url, config=crawl_config)

        if result.success:
            # 5. The extracted content is presumably JSON
            data = json.loads(result.extracted_content)
            print("Extracted items:", data)

            # 6. Show usage stats
            llm_strategy.show_usage()  # prints token usage
        else:
            print("Error:", result.error_message)

async def extract(url: str, schema):
    # 2. Create the extraction strategy
    extraction_strategy = JsonCssExtractionStrategy(schema, verbose=True)

    # 3. Set up your crawler config (if needed)
    config = CrawlerRunConfig(
        # e.g., pass js_code or wait_for if the page is dynamic
        # wait_for="css:.crypto-row:nth-child(20)"
        cache_mode = CacheMode.BYPASS,
        extraction_strategy=extraction_strategy,
    )

    async with AsyncWebCrawler(verbose=True) as crawler:
        # 4. Run the crawl and extraction
        result = await crawler.arun(
            url=url,
            config=config
        )

        if not result.success:
            print("Crawl failed:", result.error_message)
            return

        # 5. Parse the extracted JSON
        data = json.loads(result.extracted_content)
        return data
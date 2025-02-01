import os
import json
from pydantic import BaseModel
from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, CacheMode
from crawl4ai.extraction_strategy import LLMExtractionStrategy


class Article(BaseModel):
    title: str
    author: str
    summary: str
    content: str
    num_comments: int


async def extract_article(article_url: str):
    # 1. Define the LLM extraction strategy
    llm_strategy = LLMExtractionStrategy(
        provider="openai/gpt-4o-mini",  # e.g. "ollama/llama2"
        api_token=os.getenv("OPENAI_API_KEY"),
        schema=Article.model_json_schema(),
        extraction_type="schema",
        instruction="Extract the title, author, summary, content, number of comments of the article.",
        chunk_token_threshold=1000,
        overlap_rate=0.0,
        apply_chunking=True,
        input_format="markdown",  # or "html", "fit_markdown"
        extra_args={"temperature": 0.0, "max_tokens": 800},
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

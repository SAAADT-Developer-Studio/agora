from app.database.schema import Article
from langchain.chat_models import BaseChatModel
from langchain_core.output_parsers import StrOutputParser
import logging
from typing import Sequence


async def generate_cluster_titles(
    article_lists: list[list[Article]], base_model: BaseChatModel
) -> list[str]:
    # TODO: don't generate titles for clusters with only 1 article
    model = base_model | StrOutputParser()

    inputs: list[str] = [
        "You are a professional Slovenian news editor. "
        + "Generate a descriptive and engaging collective title for the following news article titles. "
        + "Write it in slovenian, output only a single title, don't include any other text or try to output markdown. Use natural capitalization (capitalize first letter only).\n\n"
        + "\n".join(
            article.title
            for article in sorted(articles[:5], key=lambda a: a.published_at, reverse=True)
        )
        for articles in article_lists
    ]
    results: Sequence[str | Exception] = await model.abatch(
        inputs=list(inputs), return_exceptions=True
    )
    # langchain returns some weird ass structure
    titles = []
    for result, articles in zip(results, article_lists):
        if isinstance(result, str):
            titles.append(result)
        else:
            # exception
            titles.append(articles[0].title)
            logging.warning(f"Failed to generate title for {len(articles)} articles: {result}")
    return titles

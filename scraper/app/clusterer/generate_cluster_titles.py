from database.schema import Article
from langchain.chat_models import BaseChatModel
from langchain_core.output_parsers import StrOutputParser
from typing import Sequence

from app.utils.llm_errors import log_llm_exceptions


def _cluster_title_prompt(articles: list[Article]) -> str:
    return (
        "You are a professional Slovenian news editor. "
        + "Generate a descriptive and engaging collective title for the following news article titles. "
        + "Write it in slovenian, output only a single title, don't include any other text or try to output markdown. Use natural capitalization (capitalize first letter only).\n\n"
        + "\n".join(
            article.title
            for article in sorted(articles[:5], key=lambda a: a.published_at, reverse=True)
        )
    )


async def generate_cluster_titles(
    article_lists: list[list[Article]], base_model: BaseChatModel
) -> list[str]:
    model = base_model | StrOutputParser()

    titles: list[str | None] = [None] * len(article_lists)
    prompts: list[str] = []
    prompt_indexes: list[int] = []
    for index, articles in enumerate(article_lists):
        if len(articles) == 1:
            titles[index] = articles[0].title
            continue
        prompts.append(_cluster_title_prompt(articles))
        prompt_indexes.append(index)

    failures: list[object] = []
    if prompts:
        results: Sequence[str | Exception] = await model.abatch(
            inputs=prompts,
            config={"max_concurrency": 4},
            return_exceptions=True,
        )
        for result, index in zip(results, prompt_indexes):
            if isinstance(result, str):
                titles[index] = result
            else:
                titles[index] = article_lists[index][0].title
                failures.append(result)
    log_llm_exceptions("Failed to generate cluster titles", failures)
    completed: list[str] = []
    for title in titles:
        if title is None:
            raise RuntimeError("cluster title was not assigned")
        completed.append(title)
    return completed

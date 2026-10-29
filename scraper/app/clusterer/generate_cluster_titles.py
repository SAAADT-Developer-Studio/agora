import asyncio
from typing import Sequence

from database.schema import Article
from langchain.chat_models import BaseChatModel
from langchain_core.output_parsers import StrOutputParser

from app.utils.llm_errors import log_llm_exceptions

# One slow OpenRouter call must not hold the clustering run open.
CLUSTER_TITLE_TIMEOUT_SECONDS = 5 * 60


def _first_nonempty_line(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    for line in value.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return None


def _article_cluster_title(article: Article) -> str:
    for candidate in (
        getattr(article, "title", None),
        getattr(article, "summary", None),
        getattr(article, "deck", None),
    ):
        line = _first_nonempty_line(candidate)
        if line:
            return line
    return "Brez naslova"


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
            titles[index] = _article_cluster_title(articles[0])
            continue
        prompts.append(_cluster_title_prompt(articles))
        prompt_indexes.append(index)

    failures: list[object] = []
    if prompts:
        try:
            results: Sequence[str | Exception] = await asyncio.wait_for(
                model.abatch(
                    inputs=prompts,
                    config={"max_concurrency": 4},
                    return_exceptions=True,
                ),
                timeout=CLUSTER_TITLE_TIMEOUT_SECONDS,
            )
        except TimeoutError:
            for index in prompt_indexes:
                titles[index] = _article_cluster_title(article_lists[index][0])
                failures.append(TimeoutError("cluster title generation timed out"))
        else:
            for result, index in zip(results, prompt_indexes):
                if isinstance(result, str) and result.strip():
                    titles[index] = result.strip()
                else:
                    titles[index] = _article_cluster_title(article_lists[index][0])
                    failures.append(result)
    log_llm_exceptions("Failed to generate cluster titles", failures)
    completed: list[str] = []
    for title in titles:
        if title is None:
            raise RuntimeError("cluster title was not assigned")
        completed.append(title)
    return completed

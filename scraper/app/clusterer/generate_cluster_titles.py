from app.database.schema import Article
from langchain.chat_models import init_chat_model
import logging


async def generate_cluster_titles(article_lists: list[list[Article]]) -> list[str]:
    # TODO: dont generate titles for clusters with only 1 article
    model = init_chat_model("gemini-2.0-flash", model_provider="google_genai")
    inputs = [
        "You are a professional Slovenian news editor. "
        + "Generate a descriptive and engaging collective title for the following news article titles. "
        + "Write it in slovenian, output only a single title, don't include any other text or try to output markdown.\n\n"
        + "\n".join(
            article.title
            for article in sorted(articles[:5], key=lambda a: a.published_at, reverse=True)
        )
        for articles in article_lists
    ]
    results = await model.abatch(inputs=list(inputs), return_exceptions=True)
    # langchain returns some weird ass structure
    titles = []
    for result, articles in zip(results, article_lists):
        if isinstance(result.content, str):
            titles.append(result.content)
        elif isinstance(result.content, list):
            titles.append(str(result.content[0]))
        else:
            # exception
            titles.append(articles[0].title)
            logging.warning(f"Failed to generate title for {len(articles)} articles: {result}")
    return titles

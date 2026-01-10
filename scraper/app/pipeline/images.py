import httpx
import logging
import asyncio

from app.providers.news_provider import ExtractedArticle, ArticleMetadata
from app.pipeline.analyzer import ArticleAnalysis
from app import config


async def search_pexels_image(query: str) -> str | None:
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                "https://api.pexels.com/v1/search",
                params={"query": query, "orientation": "landscape", "per_page": 1},
                headers={"Authorization": config.PEXELS_API_KEY},
                timeout=5.0,
            )
            response.raise_for_status()

            data = response.json()
            photos = data.get("photos", [])

            if photos:
                return photos[0]["src"]["large"]
            return None
    except Exception as e:
        logging.error(f"Error searching Pexels for '{query}': {e}")
        return None


async def search_stock_images(
    article_metadatas: list[ArticleMetadata],
    extracted_articles: list[ExtractedArticle | None],
    analyses: list[ArticleAnalysis],
) -> list[str | None]:

    tasks = []
    for article_metadata, extracted_article, analysis in zip(
        article_metadatas, extracted_articles, analyses
    ):
        # Check if article has any images
        extracted_imgs = extracted_article.image_urls if extracted_article else []
        metadata_imgs = article_metadata.image_urls or []
        has_images = len(extracted_imgs) > 0 or len(metadata_imgs) > 0

        # Search only if no images exist
        if not has_images:
            tasks.append(search_pexels_image(analysis.stock_image_search))
        else:
            tasks.append(asyncio.sleep(0, result=None))

    results = await asyncio.gather(*tasks, return_exceptions=True)
    return [None if isinstance(r, BaseException) else r for r in results]

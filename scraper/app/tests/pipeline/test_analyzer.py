from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.pipeline.analyzer import ArticleAnalysis, analyze_articles
from app.providers.news_provider import ArticleMetadata, ExtractedArticle


def _inputs():
    metadata = ArticleMetadata(
        link="https://example.com/story",
        provider_key="sta",
        image_urls=[],
        title="Naslov",
        published_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        summary="Kratek povzetek",
    )
    extracted = ExtractedArticle(
        url="https://example.com/story",
        title="Naslov",
        deck="Deck",
        content="Vsebina clanka",
    )
    return metadata, extracted


@pytest.mark.asyncio
async def test_abatch_limits_concurrency():
    analysis = ArticleAnalysis(
        summary="Povzetek",
        rank=5,
        categories=["politika"],
        stock_image_search="parliament",
        is_paywalled=False,
    )
    structured = MagicMock()
    structured.abatch = AsyncMock(return_value=[analysis])
    base_model = MagicMock()
    base_model.with_structured_output.return_value = structured
    metadata, extracted = _inputs()

    results = await analyze_articles([metadata], [extracted], base_model)

    assert results == [analysis]
    structured.abatch.assert_awaited_once()
    kwargs = structured.abatch.await_args.kwargs
    assert kwargs["config"] == {"max_concurrency": 4}
    assert kwargs["return_exceptions"] is True
    assert len(kwargs["inputs"]) == 1


@pytest.mark.asyncio
async def test_analysis_exceptions_drop_the_article():
    structured = MagicMock()
    structured.abatch = AsyncMock(return_value=[RuntimeError("timed out")])
    base_model = MagicMock()
    base_model.with_structured_output.return_value = structured
    metadata, extracted = _inputs()

    results = await analyze_articles([metadata], [None], base_model)

    assert results == [None]

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import feedparser
import pytest

from app.pipeline.analyzer import ArticleAnalysis, analyze_articles
from app.providers.sta import STAProvider

_RSS = """<?xml version="1.0"?>
<rss version="2.0"><channel><item>
<title>Vlada potrdila predlog</title>
<link>https://www.sta.si/3456789</link>
<description>Vlada je potrdila predlog zakona o davkih.</description>
</item></channel></rss>"""

_FOOTER = "© STA, Slovenska tiskovna agencija"


@pytest.mark.asyncio
async def test_sta_articles_use_rss_description_and_no_page_content():
    provider = STAProvider()

    async def unexpected_fetch(url: str) -> str:
        raise AssertionError(f"STA should not fetch article HTML: {url}")

    provider.fetch_article_html = unexpected_fetch  # type: ignore[method-assign]
    metadata = provider.parse_rss_feed_entry(feedparser.parse(_RSS).entries[0])
    extracted = await provider.extract_article(metadata.link)

    assert extracted is None
    assert metadata.title == "Vlada potrdila predlog"
    assert metadata.summary == "Vlada je potrdila predlog zakona o davkih."

    analysis = ArticleAnalysis(
        summary="Povzetek",
        rank=5,
        categories=["politika"],
        stock_image_search="parliament",
        is_paywalled=False,
    )
    structured = MagicMock()
    structured.abatch = AsyncMock(return_value=[analysis])
    model = MagicMock()
    model.with_structured_output.return_value = structured
    metadata.published_at = datetime(2026, 10, 29, tzinfo=timezone.utc)

    results = await analyze_articles([metadata], [extracted], model)

    assert results == [analysis]
    prompt = structured.abatch.await_args.kwargs["inputs"][0]
    assert "Summary: Vlada je potrdila predlog zakona o davkih." in prompt
    assert "Content:" not in prompt
    assert _FOOTER not in prompt

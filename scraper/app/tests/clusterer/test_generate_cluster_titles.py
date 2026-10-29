from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.clusterer.generate_cluster_titles import generate_cluster_titles


def _article(title: str, published_at: datetime | None = None):
    return SimpleNamespace(
        title=title,
        published_at=published_at or datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


def _model(results):
    chain = MagicMock()
    chain.abatch = AsyncMock(return_value=results)

    class FakeModel:
        def __or__(self, other):
            return chain

    return FakeModel(), chain


@pytest.mark.asyncio
async def test_abatch_limits_concurrency():
    model, chain = _model(["Skupni naslov"])
    older = _article("Starejsi", datetime(2026, 1, 1, tzinfo=timezone.utc))
    newer = _article("Novejsi", datetime(2026, 1, 2, tzinfo=timezone.utc))

    titles = await generate_cluster_titles([[older, newer]], model)

    assert titles == ["Skupni naslov"]
    chain.abatch.assert_awaited_once()
    kwargs = chain.abatch.await_args.kwargs
    assert kwargs["config"] == {"max_concurrency": 4}
    assert kwargs["return_exceptions"] is True
    prompt = kwargs["inputs"][0]
    assert prompt.index("Novejsi") < prompt.index("Starejsi")


@pytest.mark.asyncio
async def test_singleton_clusters_skip_the_llm():
    model, chain = _model(["unused"])

    titles = await generate_cluster_titles(
        [[_article("Samo eden")], [_article("Tudi eden")]],
        model,
    )

    assert titles == ["Samo eden", "Tudi eden"]
    chain.abatch.assert_not_called()


@pytest.mark.asyncio
async def test_mixed_clusters_only_send_multi_article_prompts():
    model, chain = _model(["Skupni naslov"])
    single = _article("Samostojen")
    multi = [_article("Prvi"), _article("Drugi")]

    titles = await generate_cluster_titles(
        [[single], multi, [_article("Se eden")]],
        model,
    )

    assert titles == ["Samostojen", "Skupni naslov", "Se eden"]
    inputs = chain.abatch.await_args.kwargs["inputs"]
    assert len(inputs) == 1
    assert "Prvi" in inputs[0]
    assert "Drugi" in inputs[0]
    assert "Samostojen" not in inputs[0]


@pytest.mark.asyncio
async def test_llm_failure_uses_first_article_title():
    model, chain = _model([RuntimeError("connection dropped")])
    first = _article("Prvi naslov")
    second = _article("Drugi naslov")

    titles = await generate_cluster_titles([[first, second]], model)

    assert titles == ["Prvi naslov"]

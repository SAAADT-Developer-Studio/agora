import json
from datetime import datetime, timedelta, timezone

from clusterer.replay import (
    Article,
    Dataset,
    LLMCache,
    Spend,
    cached_models,
    no_llm_models,
    replay,
    report,
)
from clusterer.summary import Brief, Bullet

_START = datetime(2026, 10, 20, 0, tzinfo=timezone.utc)


def _article(article_id: int, embedding: list[float], hours: float, prod: int) -> Article:
    at = _START + timedelta(hours=hours)
    return Article(
        id=article_id,
        title=f"Naslov {article_id}",
        deck=None,
        summary="Povzetek",
        published_at=at,
        embedding=embedding,
        prod_story_id=prod,
        prod_method="cosine",
        prod_assigned_at=at + timedelta(minutes=10),
    )


def _dataset() -> Dataset:
    return Dataset(
        start=_START,
        end=_START + timedelta(hours=6),
        context=[_article(1, [1.0, 0.0], -5, 500)],
        window=[
            _article(2, [1.0, 0.0], 1, 500),
            _article(3, [0.0, -1.0], 2, 600),
            _article(4, [0.70, 0.714], 3, 500),
        ],
        briefs={500: Brief("Zgodba", (Bullet("Dejstvo ena", (1,)),), 1, _START)},
        prod_titles={500: "Zgodba", 600: "Druga"},
    )


def test_no_llm_replay_joins_from_context_and_seeds_the_rest() -> None:
    dataset = _dataset()

    store = replay(dataset, no_llm_models())

    assert store.memberships[2].story_id == 500
    assert store.memberships[3].story_id >= 100_000_000
    assert store.memberships[4].method == "seed"
    text = report(dataset, store, None)
    assert "Agreement with production" in text


def test_cached_replies_are_reused(tmp_path, monkeypatch) -> None:
    dataset = _dataset()
    calls: list[str] = []

    def chat(prompt: str, *, response_format: dict, max_tokens: int | None = None):
        from clusterer.llm import Reply

        calls.append(prompt)
        if response_format["json_schema"]["name"] == "story_choice":
            return Reply(json.dumps({"story": 1, "relation": "same_event"}), 0.001)
        if response_format["json_schema"]["name"] == "story_relation":
            return Reply(json.dumps({"relation": "different"}), 0.001)
        return Reply(json.dumps({"title": "Nov naslov zgodbe", "bullets": []}), 0.001)

    monkeypatch.setattr("clusterer.llm.chat", chat)
    path = tmp_path / "cache.jsonl"

    first = Spend(max_usd=1, max_calls=100)
    store = replay(dataset, cached_models(LLMCache(path, first)))
    second = Spend(max_usd=1, max_calls=100)
    replay(dataset, cached_models(LLMCache(path, second)))

    assert store.memberships[4].story_id == 500
    assert store.memberships[4].relation == "same_event"
    assert first.calls == len(calls) > 0
    assert second.calls == 0
    assert second.cached == first.calls

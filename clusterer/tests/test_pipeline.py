from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from clusterer.assign import NeighborIndex, Verdict
from clusterer.pipeline import MergeMemory, Models, run_batch
from clusterer.replay import Article, MemoryStore

_T0 = datetime(2026, 10, 20, 9, tzinfo=timezone.utc)


def _article(article_id: int, embedding: list[float], minutes: int = 0) -> Article:
    return Article(
        id=article_id,
        title=f"Article {article_id}",
        deck=None,
        summary=None,
        published_at=_T0 + timedelta(minutes=minutes),
        embedding=embedding,
        prod_story_id=None,
        prod_method=None,
        prod_assigned_at=None,
    )


@dataclass
class _Calls:
    merges: int = 0


def _models(merge_answer: str | None, calls: _Calls) -> Models:
    def merge_relation(*_args: object) -> str | None:
        calls.merges += 1
        return merge_answer

    return Models(
        judge=lambda *_args: Verdict(None, "different"),
        merge_relation=merge_relation,
        summarize=lambda *_args, **_kwargs: None,
    )


def _two_close_seeds() -> tuple[NeighborIndex, MemoryStore, list[Article]]:
    # Too far apart to join (0.70 < 0.75) but their centroids score as a merge
    # pair once a third article lands between them.
    articles = [
        _article(1, [1.0, 0.0, 0.0]),
        _article(2, [0.70, 0.714, 0.0], 1),
        _article(3, [0.92, 0.39, 0.0], 2),
    ]
    store = MemoryStore({a.id: a for a in articles}, [_T0])
    return NeighborIndex(), store, articles


def test_development_merges_duplicate_stories() -> None:
    index, store, articles = _two_close_seeds()
    calls = _Calls()

    stats = run_batch(
        index, articles, store, _models("development", calls), now=_T0, memory=MergeMemory()
    )

    assert stats.merged == 1
    assert len({m.story_id for m in store.memberships.values()}) == 1
    assert store.merged_into


def test_rejected_pair_is_not_asked_again_until_it_grows() -> None:
    index, store, articles = _two_close_seeds()
    calls = _Calls()
    memory = MergeMemory()
    models = _models("related_topic", calls)

    run_batch(index, articles, store, models, now=_T0, memory=memory)
    asked = calls.merges
    later = _article(4, [0.0, 0.0, 1.0], 3)
    store.articles[later.id] = later
    run_batch(index, [later], store, models, now=_T0, memory=memory)

    assert asked >= 1
    assert calls.merges == asked
    assert not store.merged_into

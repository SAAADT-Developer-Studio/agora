from datetime import datetime, timezone

from clusterer.assign import COSINE, JOIN_THRESHOLD, LLM, LLM_FLOOR, SEED, NeighborIndex, decide


def test_empty_index_seeds() -> None:
    assignment = decide([1.0, 0.0], NeighborIndex())
    assert assignment.story_id is None
    assert assignment.method == SEED
    assert assignment.similarity is None
    assert assignment.nearest_article_id is None


def test_identical_embedding_joins() -> None:
    index = NeighborIndex()
    index.add(article_id=1, story_id=10, embedding=[1.0, 0.0])

    assignment = decide([1.0, 0.0], index)

    assert assignment.story_id == 10
    assert assignment.method == COSINE
    assert assignment.nearest_article_id == 1
    assert assignment.similarity == 1.0


def test_below_threshold_seeds() -> None:
    index = NeighborIndex()
    index.add(article_id=1, story_id=10, embedding=[1.0, 0.0])

    assignment = decide([0.0, 1.0], index)

    assert assignment.story_id is None
    assert assignment.method == SEED
    assert assignment.similarity is None
    assert assignment.nearest_article_id is None


def test_just_above_threshold_joins() -> None:
    index = NeighborIndex()
    index.add(article_id=1, story_id=10, embedding=[1.0, 0.0])
    above = JOIN_THRESHOLD + 0.01
    embedding = [above, (1.0 - above**2) ** 0.5]

    def judge(*_args: object) -> bool:
        raise AssertionError("judge should not be called")

    assignment = decide(embedding, index, judge=judge)

    assert assignment.story_id == 10
    assert assignment.method == COSINE
    assert assignment.similarity is not None
    assert assignment.similarity > JOIN_THRESHOLD


def test_just_below_floor_seeds() -> None:
    index = NeighborIndex()
    index.add(article_id=1, story_id=10, embedding=[1.0, 0.0])
    below = LLM_FLOOR - 0.01
    embedding = [below, (1.0 - below**2) ** 0.5]
    calls: list[object] = []

    def judge(*args: object) -> bool:
        calls.append(args)
        return True

    assignment = decide(embedding, index, judge=judge)

    assert calls == []
    assert assignment.story_id is None
    assert assignment.method == SEED


def test_later_article_in_batch_can_join_earlier_seed() -> None:
    index = NeighborIndex()
    first = decide([1.0, 0.0], index)
    assert first.method == SEED

    index.add(article_id=1, story_id=42, embedding=[1.0, 0.0])
    second = decide([1.0, 0.0], index)

    assert second.story_id == 42
    assert second.method == COSINE
    assert second.nearest_article_id == 1


def _toward(cosine: float) -> list[float]:
    return [cosine, (1.0 - cosine**2) ** 0.5]


def _at(hour: int) -> datetime:
    return datetime(2026, 9, 27, hour, tzinfo=timezone.utc)


def test_gray_band_yes_joins_as_llm() -> None:
    index = NeighborIndex()
    index.add(1, 10, [1.0, 0.0], title="Nearest", summary="Near", is_seed=True)
    seen: dict[str, object] = {}

    def judge(title: str, summary: str | None, members: list[tuple[str, str | None]]) -> bool:
        seen["title"] = title
        seen["summary"] = summary
        seen["members"] = members
        return True

    assignment = decide(_toward(0.74), index, title="New", summary="Body", judge=judge)

    assert assignment.story_id == 10
    assert assignment.method == LLM
    assert assignment.nearest_article_id == 1
    assert assignment.similarity is not None
    assert abs(assignment.similarity - 0.74) < 1e-9
    assert seen == {"title": "New", "summary": "Body", "members": [("Nearest", "Near")]}


def test_gray_band_no_seeds() -> None:
    index = NeighborIndex()
    index.add(1, 10, [1.0, 0.0], title="Nearest", summary="Near", is_seed=True)

    assignment = decide(_toward(0.74), index, title="New", summary="Body", judge=lambda *_: False)

    assert assignment.story_id is None
    assert assignment.method == SEED
    assert assignment.similarity is None
    assert assignment.nearest_article_id is None


def test_gray_band_error_seeds() -> None:
    index = NeighborIndex()
    index.add(1, 10, [1.0, 0.0], title="Nearest", summary="Near", is_seed=True)

    def judge(*_args: object) -> bool:
        raise RuntimeError("down")

    assignment = decide(_toward(LLM_FLOOR), index, title="New", summary=None, judge=judge)

    assert assignment.method == SEED
    assert assignment.story_id is None


def test_gray_band_without_judge_seeds() -> None:
    index = NeighborIndex()
    index.add(1, 10, [1.0, 0.0])

    assignment = decide(_toward(0.74), index)

    assert assignment.method == SEED


def test_prompt_members_prefers_nearest_seed_and_newest() -> None:
    index = NeighborIndex()
    index.add(1, 10, [1.0, 0.0], title="seed", summary="s", published_at=_at(1), is_seed=True)
    index.add(2, 10, [1.0, 0.0], title="mid", summary=None, published_at=_at(2))
    index.add(3, 10, [1.0, 0.0], title="newer", summary="n", published_at=_at(3))
    index.add(4, 10, [0.0, 1.0], title="nearest", summary="near", published_at=_at(4))
    index.add(5, 10, [1.0, 0.0], title="newest", summary="new", published_at=_at(5))

    assert index.prompt_members(10, nearest_article_id=4) == [
        ("nearest", "near"),
        ("seed", "s"),
        ("newest", "new"),
        ("newer", "n"),
    ]


def test_prompt_members_does_not_repeat_the_seed() -> None:
    index = NeighborIndex()
    index.add(1, 10, [1.0, 0.0], title="only", summary=None, published_at=_at(1), is_seed=True)

    assert index.prompt_members(10, 1) == [("only", None)]

from datetime import datetime, timedelta, timezone

import math

from clusterer.assign import (
    COSINE,
    JUDGE_CANDIDATES,
    DEVELOPMENT_FLOOR,
    SAME_EVENT_FLOOR,
    Verdict,
    JOIN_THRESHOLD,
    LLM,
    LLM_FLOOR,
    SEED,
    STORY_SPAN,
    NeighborIndex,
    PromptArticle,
    StoryContext,
    decide,
)


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


def _unit(degrees: float) -> list[float]:
    radians = math.radians(degrees)
    return [math.cos(radians), math.sin(radians)]


def test_gray_band_yes_joins_as_llm() -> None:
    index = NeighborIndex()
    index.add(1, 10, [1.0, 0.0], title="Nearest", summary="Near", published_at=_at(1), is_seed=True)
    seen: dict[str, object] = {}

    def judge(article: PromptArticle, stories: list[StoryContext]) -> Verdict:
        seen["article"] = article
        seen["story"] = stories[0]
        return Verdict(0, "same_event")

    assignment = decide(
        _toward(0.74), index, title="New", summary="Body", published_at=_at(2), judge=judge
    )

    assert assignment.story_id == 10
    assert assignment.method == LLM
    assert assignment.nearest_article_id == 1
    assert assignment.similarity is not None
    assert abs(assignment.similarity - 0.74) < 1e-9
    assert assignment.relation == "same_event"
    assert seen == {
        "article": PromptArticle("New", "Body", _at(2)),
        "story": StoryContext(
            headline=None, bullets=(), members=(PromptArticle("Nearest", "Near", _at(1)),)
        ),
    }


def test_close_to_one_member_but_far_from_story_goes_to_judge() -> None:
    # The story drifted: the seed is near the new article, the other members
    # point elsewhere, so the story centroid is far from it.
    index = NeighborIndex()
    index.add(1, 10, [1.0, 0.0, 0.0], is_seed=True)
    for article_id in (2, 3, 4):
        index.add(article_id, 10, [0.0, 0.0, 1.0])
    calls: list[object] = []

    def judge(*args: object) -> Verdict:
        calls.append(args)
        return Verdict(None, "related_topic")

    assignment = decide([0.866, 0.5, 0.0], index, judge=judge)

    assert len(calls) == 1
    assert assignment.method == SEED
    assert assignment.relation == "related_topic"


def test_cosine_join_records_story_similarity() -> None:
    index = NeighborIndex()
    index.add(1, 10, _unit(0))
    index.add(2, 10, _unit(10))

    assignment = decide(_unit(5), index)

    assert assignment.method == COSINE
    assert assignment.story_similarity is not None
    assert abs(assignment.story_similarity - 1.0) < 1e-9


def test_judge_sees_story_closest_to_its_centroid() -> None:
    # Story 10's nearest member is closer, but story 20 matches as a whole.
    index = NeighborIndex()
    index.add(1, 10, [0.819, 0.574, 0.0], title="ten-near")
    index.add(2, 10, [0.0, 0.0, 1.0], title="ten-far")
    index.add(3, 20, [0.72, -0.694, 0.0], title="twenty-a")
    index.add(4, 20, [0.72, -0.694, 0.0], title="twenty-b")
    seen: list[list[StoryContext]] = []

    def judge(_article: PromptArticle, stories: list[StoryContext]) -> Verdict:
        seen.append(stories)
        return Verdict(0, "same_event")

    assignment = decide([1.0, 0.0, 0.0], index, judge=judge)

    assert assignment.story_id == 20
    assert assignment.method == LLM
    assert {member.title for member in seen[0][0].members} == {"twenty-a", "twenty-b"}
    assert {member.title for member in seen[0][1].members} == {"ten-near", "ten-far"}


def test_story_context_includes_brief_and_fewer_members() -> None:
    index = NeighborIndex()
    for article_id in range(1, 6):
        index.add(article_id, 10, [1.0, 0.0], title=str(article_id), published_at=_at(article_id))
    index.set_brief(10, "Headline", ["One", "Two"])

    context = index.story_context(10)

    assert context.headline == "Headline"
    assert context.bullets == ("One", "Two")
    assert [member.title for member in context.members] == ["5", "4", "3"]


def test_gray_band_no_seeds() -> None:
    index = NeighborIndex()
    index.add(1, 10, [1.0, 0.0], title="Nearest", summary="Near", is_seed=True)

    assignment = decide(
        _toward(0.74), index, title="New", summary="Body", judge=lambda *_: Verdict(None, "different")
    )

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

    assert [member.title for member in index.prompt_members(10, nearest_article_id=4)] == [
        "nearest",
        "seed",
        "newest",
        "newer",
    ]


def test_prompt_members_does_not_repeat_the_seed() -> None:
    index = NeighborIndex()
    index.add(1, 10, [1.0, 0.0], title="only", summary=None, published_at=_at(1), is_seed=True)

    assert index.prompt_members(10, 1) == [PromptArticle("only", None, _at(1))]


def test_merge_candidates_need_a_changed_story_and_close_centroids() -> None:
    index = NeighborIndex()
    index.add(1, 10, _unit(0))
    index.add(2, 10, _unit(2))
    index.add(3, 20, _unit(4))
    index.add(4, 30, _unit(90))

    assert index.merge_candidates(changed=set()) == []
    pairs = index.merge_candidates(changed={20})
    assert [(pair.keep_story_id, pair.drop_story_id) for pair in pairs] == [(10, 20)]
    assert index.merge_candidates(changed={30}) == []


def test_move_relabels_members_and_centroid() -> None:
    index = NeighborIndex()
    index.add(1, 10, _unit(0), is_seed=True)
    index.add(2, 20, _unit(4), is_seed=True)
    index.set_brief(20, "Old", ["gone"])

    index.move(20, 10)

    assert index.size(10) == 2
    assert index.size(20) == 0
    assert [candidate.story_id for candidate in index.candidates(_unit(2))] == [10]
    assert index.story_context(20).headline is None


def _story_of(index: NeighborIndex, story_id: int, degrees: float, first_id: int) -> None:
    for offset in range(3):
        index.add(first_id + offset, story_id, _unit(degrees), title=f"{story_id}-{offset}")


def test_judge_can_pick_the_runner_up_story() -> None:
    # Story 20 is a hair further by centroid; the judge sees both and picks it.
    index = NeighborIndex()
    _story_of(index, 10, 44, 1)
    _story_of(index, 20, -45, 10)

    def judge(_article: PromptArticle, stories: list[StoryContext]) -> Verdict:
        assert [s.members[0].title.split("-")[0] for s in stories] == ["10", "20"]
        return Verdict(1, "same_event")

    assignment = decide(_unit(0), index, judge=judge)

    assert assignment.story_id == 20
    assert assignment.method == LLM


def test_judge_sees_at_most_a_few_stories() -> None:
    index = NeighborIndex()
    for story in range(JUDGE_CANDIDATES + 2):
        index.add(story, story, _unit(42 + story))
    seen: list[int] = []

    def judge(_article: PromptArticle, stories: list[StoryContext]) -> Verdict:
        seen.append(len(stories))
        return Verdict(None, "different")

    decide(_unit(0), index, judge=judge)

    assert seen == [JUDGE_CANDIDATES]


def test_development_far_from_the_story_seeds() -> None:
    index = NeighborIndex()
    index.add(1, 10, [1.0, 0.0])
    between = (SAME_EVENT_FLOOR + DEVELOPMENT_FLOOR) / 2

    development = decide(_toward(between), index, judge=lambda *_: Verdict(0, "development"))
    same = decide(_toward(between), index, judge=lambda *_: Verdict(0, "same_event"))

    assert development.method == SEED
    assert development.relation == "development"
    assert same.method == LLM


def test_same_event_far_from_the_story_seeds() -> None:
    index = NeighborIndex()
    index.add(1, 10, [1.0, 0.0])

    same = decide(
        _toward(SAME_EVENT_FLOOR - 0.02), index, judge=lambda *_: Verdict(0, "same_event")
    )

    assert same.method == SEED
    assert same.relation == "same_event"


def test_judge_unavailable_seeds() -> None:
    index = NeighborIndex()
    index.add(1, 10, [1.0, 0.0])

    assert decide(_toward(0.74), index, judge=lambda *_: None).method == SEED


def test_merge_candidates_match_a_big_story_by_its_members() -> None:
    # Story 10 has drifted over two developments; its centroid is far from
    # story 20, but story 20 duplicates one of them.
    index = NeighborIndex()
    for article_id in range(1, 5):
        index.add(article_id, 10, [1.0, 0.0, 0.0])
    for article_id in range(5, 9):
        index.add(article_id, 10, [0.0, 0.0, 1.0])
    index.add(20, 20, [0.98, 0.2, 0.0])
    index.add(21, 20, [0.98, -0.2, 0.0])

    pairs = index.merge_candidates(changed={20})

    assert [(p.keep_story_id, p.drop_story_id) for p in pairs] == [(10, 20)]
    assert pairs[0].similarity > 0.95


T0 = datetime(2026, 10, 11, 8, tzinfo=timezone.utc)


def test_story_stops_taking_articles_after_its_span() -> None:
    index = NeighborIndex()
    index.add(1, 10, _unit(0), published_at=T0)
    index.add(2, 10, _unit(0), published_at=T0 + timedelta(days=2))

    inside = decide(_unit(0), index, published_at=T0 + STORY_SPAN)
    after = decide(_unit(0), index, published_at=T0 + STORY_SPAN + timedelta(minutes=1))

    assert inside.story_id == 10
    assert after.story_id is None
    assert after.method == SEED


def test_story_span_counts_members_outside_the_window() -> None:
    index = NeighborIndex()
    index.add(1, 10, _unit(0), published_at=T0 + timedelta(days=2))
    index.set_started(10, T0 - timedelta(days=2))

    assert decide(_unit(0), index, published_at=T0 + timedelta(days=2)).story_id is None


def test_closed_story_takes_no_merges() -> None:
    index = NeighborIndex()
    index.add(1, 10, _unit(0), published_at=T0)
    index.add(2, 10, _unit(2), published_at=T0 + timedelta(days=2))
    index.add(3, 20, _unit(1), published_at=T0 + timedelta(days=2))

    open_pairs = index.merge_candidates({20}, at=T0 + timedelta(days=2))
    closed_pairs = index.merge_candidates({20}, at=T0 + timedelta(days=4))

    assert [(p.keep_story_id, p.drop_story_id) for p in open_pairs] == [(10, 20)]
    assert closed_pairs == []


def test_merged_story_keeps_the_earlier_start() -> None:
    index = NeighborIndex()
    index.add(1, 10, _unit(0), published_at=T0 + timedelta(days=2))
    index.add(2, 20, _unit(0), published_at=T0)

    index.move(20, 10)

    assert not index.is_open(10, T0 + timedelta(days=4))

"""Hidden stories stay hidden, and the LLM steps that do not assign articles are skipped."""

from datetime import datetime, timezone
from types import SimpleNamespace

from database.repositories import AssignedArticle, StoryRepository
from database.schema import Story, StoryArticle

from clusterer.assign import NeighborIndex
from clusterer.run import _assign_unassigned, _merge_duplicates, _refresh_summary


NOW = datetime(2026, 11, 17, tzinfo=timezone.utc)


class _Session:
    def __init__(self):
        self.created: list[Story] = []

    def flush(self):
        next_id = 50
        for story in self.created:
            if getattr(story, "id", None) is None:
                story.id = next_id
                next_id += 1

    def execute(self, statement):
        return statement

    def expire(self, obj, attrs):
        return None


class _Stories:
    def __init__(self, session, assigned, unassigned, by_id):
        self.session = session
        self.assigned = assigned
        self.unassigned = unassigned
        self.by_id = by_id
        self.memberships: list[StoryArticle] = []
        self.summary_ids: list[int] = []

    def get_assigned_since(self, since):
        return self.assigned

    def get_unassigned_since(self, since):
        return self.unassigned

    def get_by_ids(self, story_ids):
        return {story_id: self.by_id[story_id] for story_id in story_ids}

    def latest_summaries(self, story_ids):
        return {}

    def create(self, story):
        self.session.created.append(story)
        self.by_id[None] = story

    def add_membership(self, membership):
        self.memberships.append(membership)

    def member_texts(self, story_id):
        self.summary_ids.append(story_id)
        return []

    def latest_summary(self, story_id):
        return None

    def add_summary(self, summary):
        raise AssertionError("hidden story wrote a summary")

    def merge(self, drop, keep):
        StoryRepository(self.session).merge(drop, keep)


def _story(story_id: int, *, hidden: bool) -> Story:
    story = Story(title=f"story-{story_id}", last_article_published_at=NOW, hidden=hidden)
    story.id = story_id
    return story


def _uow(stories):
    return SimpleNamespace(stories=stories, session=stories.session)


def test_cosine_article_joins_a_hidden_story_without_a_summary_refresh(monkeypatch):
    hidden = _story(1, hidden=True)
    session = _Session()
    assigned = [
        AssignedArticle(10, 1, [1.0, 0.0], "Old", "old", NOW, "cosine"),
    ]
    article = SimpleNamespace(
        id=11, embedding=[1.0, 0.0], title="New", summary="new", published_at=NOW,
    )
    stories = _Stories(session, assigned, [article], {1: hidden})

    def judge(*_args):
        raise AssertionError("judge should not run for a cosine join")

    monkeypatch.setattr("clusterer.run.same_happening", judge)
    _assign_unassigned(_uow(stories))

    assert [membership.story_id for membership in stories.memberships] == [1]
    assert hidden.hidden is True
    assert stories.summary_ids == []
    assert session.created == []


def test_gray_band_article_seeds_instead_of_judging_a_hidden_story(monkeypatch):
    hidden = _story(1, hidden=True)
    session = _Session()
    assigned = [
        AssignedArticle(10, 1, [1.0, 0.0], "Old", "old", NOW, "seed"),
    ]
    # 0.74 is below the cosine join threshold and above the judge floor.
    article = SimpleNamespace(
        id=11, embedding=[0.74, (1 - 0.74**2) ** 0.5], title="New", summary="new",
        published_at=NOW,
    )
    stories = _Stories(session, assigned, [article], {1: hidden})
    calls = []

    def judge(*args):
        calls.append(args)
        return True

    monkeypatch.setattr("clusterer.run.same_happening", judge)
    _assign_unassigned(_uow(stories))

    assert calls == []
    assert session.created
    assert session.created[0].hidden is False
    assert stories.memberships[0].story_id == session.created[0].id
    assert stories.memberships[0].story_id != hidden.id
    assert hidden.id not in stories.summary_ids


def test_refresh_summary_returns_before_reading_a_hidden_story():
    story = _story(4, hidden=True)

    class Stories:
        def member_texts(self, story_id):
            raise AssertionError("member text was loaded")

    _refresh_summary(SimpleNamespace(stories=Stories(), session=_Session()), story, NeighborIndex())


def test_merge_with_a_hidden_story_hides_the_survivor_and_skips_its_summary(monkeypatch):
    judged = []

    def same_story(*args):
        judged.append(args)
        return True

    monkeypatch.setattr("clusterer.run.same_story", same_story)
    keep = _story(1, hidden=False)
    drop = _story(2, hidden=True)
    session = _Session()
    stories = _Stories(session, [], [], {1: keep, 2: drop})
    index = NeighborIndex()
    index.add(1, 1, [1.0, 0.0])
    index.add(2, 2, [1.0, 0.0])

    _merge_duplicates(_uow(stories), index, {1: keep, 2: drop}, changed={1})

    assert judged
    assert keep.hidden is True
    assert drop.merged_into_story_id == 1
    assert stories.summary_ids == []


def test_two_hidden_stories_are_not_judged_or_merged(monkeypatch):
    def same_story(*_args):
        raise AssertionError("both stories are already hidden")

    monkeypatch.setattr("clusterer.run.same_story", same_story)
    keep = _story(1, hidden=True)
    drop = _story(2, hidden=True)
    session = _Session()
    stories = _Stories(session, [], [], {1: keep, 2: drop})
    index = NeighborIndex()
    index.add(1, 1, [1.0, 0.0])
    index.add(2, 2, [1.0, 0.0])

    _merge_duplicates(_uow(stories), index, {1: keep, 2: drop}, changed={2})

    assert drop.merged_into_story_id is None
    assert stories.summary_ids == []


def test_visible_merge_still_refreshes_the_summary(monkeypatch):
    monkeypatch.setattr("clusterer.run.same_story", lambda *_args: True)
    keep = _story(1, hidden=False)
    drop = _story(2, hidden=False)
    session = _Session()
    stories = _Stories(session, [], [], {1: keep, 2: drop})
    index = NeighborIndex()
    index.add(1, 1, [1.0, 0.0])
    index.add(2, 2, [1.0, 0.0])

    _merge_duplicates(_uow(stories), index, {1: keep, 2: drop}, changed={1})

    assert keep.hidden is False
    assert stories.summary_ids == [1]

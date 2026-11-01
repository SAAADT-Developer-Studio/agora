"""One clusterer pass over a batch of new articles, independent of storage.

Production (``run.py``) backs it with the database, the replay harness
(``replay.py``) with memory. Both call ``run_batch``, so a replay exercises
the code that ships.
"""

import logging
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Protocol

from . import judge as judge_module
from . import summary as summary_module
from .assign import LLM, SEED, Assignment, Judge, NeighborIndex, StoryContext, decide
from .judge import MERGE_RELATIONS
from .summary import ArticleExcerpt, Brief, lead_article

# Articles published this long ago are neither assigned nor matched against.
WINDOW_DAYS = 3
# A rejected merge pair is asked again once its smaller story gained this many
# articles. Without it, two big neighbouring stories are re-judged every run.
MERGE_REASK_GROWTH = 3

logger = logging.getLogger(__name__)


class NewArticle(Protocol):
    id: int
    title: str
    summary: str | None
    embedding: Sequence[float]
    published_at: datetime


class AssignedRow(Protocol):
    article_id: int
    story_id: int
    embedding: Sequence[float]
    title: str
    summary: str | None
    published_at: datetime
    method: str


class Store(Protocol):
    def create_story(self, article: NewArticle) -> int: ...

    def add_membership(self, story_id: int, article: NewArticle, assignment: Assignment) -> None: ...

    def merge(self, drop_id: int, keep_id: int) -> None: ...

    def excerpts(self, story_id: int) -> list[ArticleExcerpt]: ...

    def latest_brief(self, story_id: int) -> Brief | None: ...

    def save_brief(self, story_id: int, brief: Brief) -> None: ...

    def set_title(self, story_id: int, title: str) -> None: ...


Summarize = Callable[..., Brief | None]
MergeJudge = Callable[[StoryContext, StoryContext], str | None]


@dataclass(frozen=True)
class Models:
    """The LLM-backed steps. The replay harness swaps in cached versions."""

    judge: Judge
    merge_relation: MergeJudge
    summarize: Summarize

    @classmethod
    def production(cls) -> "Models":
        return cls(
            judge=judge_module.choose_story,
            merge_relation=judge_module.story_relation,
            summarize=summary_module.refresh_brief,
        )


@dataclass
class MergeMemory:
    """Rejected merge pairs, keyed by sorted story ids, with the smaller size then."""

    rejected: dict[tuple[int, int], int] = field(default_factory=dict)

    def should_ask(self, pair: tuple[int, int], smaller: int) -> bool:
        before = self.rejected.get(pair)
        return before is None or smaller >= before + MERGE_REASK_GROWTH

    def reject(self, pair: tuple[int, int], smaller: int) -> None:
        self.rejected[pair] = smaller


@dataclass
class BatchStats:
    seeded: int = 0
    cosine: int = 0
    llm: int = 0
    merged: int = 0


def load_index(
    rows: Iterable[AssignedRow],
    briefs: Mapping[int, Brief],
    started: Mapping[int, datetime] | None = None,
) -> NeighborIndex:
    """``started`` holds each story's first article, which may predate the window."""
    index = NeighborIndex()
    for row in rows:
        index.add(
            row.article_id,
            row.story_id,
            row.embedding,
            title=row.title,
            summary=row.summary,
            published_at=row.published_at,
            is_seed=row.method == SEED,
        )
    for story_id, at in (started or {}).items():
        index.set_started(story_id, at)
    for story_id, brief in briefs.items():
        index.set_brief(story_id, brief.title, _context_lines(brief))
    return index


def _context_lines(brief: Brief) -> list[str]:
    """What the judge reads of a summary: the lede, which carries the date, then bullets."""
    lines = [bullet.text for bullet in brief.bullets]
    return [brief.lede, *lines] if brief.lede else lines


def run_batch(
    index: NeighborIndex,
    articles: Sequence[NewArticle],
    store: Store,
    models: Models,
    *,
    now: datetime,
    memory: MergeMemory,
) -> BatchStats:
    """Assign each article in order, then merge stories that turned out duplicates."""
    stats = BatchStats()
    changed: set[int] = set()
    for article in articles:
        assignment = decide(
            article.embedding,
            index,
            title=article.title,
            summary=article.summary,
            published_at=article.published_at,
            judge=models.judge,
        )
        if assignment.story_id is None:
            story_id = store.create_story(article)
            stats.seeded += 1
        else:
            story_id = assignment.story_id
            if assignment.method == LLM:
                stats.llm += 1
            else:
                stats.cosine += 1
        store.add_membership(story_id, article, assignment)
        index.add(
            article.id,
            story_id,
            article.embedding,
            title=article.title,
            summary=article.summary,
            published_at=article.published_at,
            is_seed=assignment.story_id is None,
        )
        changed.add(story_id)
        _refresh_summary(store, story_id, index, models, now=now)
    stats.merged = _merge_duplicates(store, index, models, changed, now=now, memory=memory)
    return stats


def _merge_duplicates(
    store: Store,
    index: NeighborIndex,
    models: Models,
    changed: set[int],
    *,
    now: datetime,
    memory: MergeMemory,
) -> int:
    """Merge stories that cover the same happening, e.g. after two seeds grew side by side."""
    merged: set[int] = set()
    for pair in index.merge_candidates(changed, at=now):
        if pair.keep_story_id in merged or pair.drop_story_id in merged:
            continue
        key = tuple(sorted((pair.keep_story_id, pair.drop_story_id)))
        smaller = index.size(pair.drop_story_id)
        if not memory.should_ask(key, smaller):
            continue
        try:
            relation = models.merge_relation(
                index.story_context(pair.keep_story_id), index.story_context(pair.drop_story_id)
            )
        except Exception:
            logger.warning("Story merge judge failed", exc_info=True)
            continue
        logger.info(
            "Merge judge: story %s -> %s is %s (score %.3f)",
            pair.drop_story_id,
            pair.keep_story_id,
            relation,
            pair.similarity,
        )
        if relation not in MERGE_RELATIONS:
            if relation is not None:
                memory.reject(key, smaller)
            continue
        store.merge(pair.drop_story_id, pair.keep_story_id)
        index.move(pair.drop_story_id, pair.keep_story_id)
        merged.add(pair.drop_story_id)
        logger.info(
            "Merged story %s into %s (score %.3f)",
            pair.drop_story_id,
            pair.keep_story_id,
            pair.similarity,
        )
        _refresh_summary(store, pair.keep_story_id, index, models, now=now, force=True)
    return len(merged)


def _refresh_summary(
    store: Store,
    story_id: int,
    index: NeighborIndex,
    models: Models,
    *,
    now: datetime,
    force: bool = False,
) -> None:
    excerpts = store.excerpts(story_id)
    previous = store.latest_brief(story_id)
    brief = models.summarize(excerpts, previous, force=force, now=now)
    if brief is None:
        lead = lead_article(excerpts)
        if previous is None and lead is not None:
            store.set_title(story_id, lead.title)
        return
    brief = replace(brief, created_at=now)
    store.save_brief(story_id, brief)
    index.set_brief(story_id, brief.title, _context_lines(brief))
    logger.info("Story %s summary: %s (%d bullets)", story_id, brief.title, len(brief.bullets))

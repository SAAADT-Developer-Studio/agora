"""Assignment: an article joins the story it matches, or seeds a new one.

A story is scored as a whole, not by its single closest article. The nearest
member must be close (``JOIN_THRESHOLD``) and the article must also be close
to the story's centroid (``STORY_THRESHOLD``). Matching one member is not
enough, so a story cannot drift link by link: A pulls in B, B pulls in C,
until C has nothing to do with A. Articles that match a member but not the
story's core go to the judge.
"""

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timezone

import numpy as np

JOIN_THRESHOLD = 0.75
# Cosine to the story centroid. On the dev data every existing cosine join
# scores >= 0.756 and the nearest other story of a seed is <= 0.76.
STORY_THRESHOLD = 0.70
LLM_FLOOR = 0.55
# Centroid-to-centroid cosine above which two stories go to the merge judge.
MERGE_THRESHOLD = 0.80
SEED = "seed"
COSINE = "cosine"
LLM = "llm"

_PROMPT_MEMBERS = 4
_PROMPT_MEMBERS_WITH_BRIEF = 3

logger = logging.getLogger(__name__)
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


@dataclass(frozen=True)
class PromptArticle:
    title: str
    summary: str | None
    published_at: datetime | None = None


@dataclass(frozen=True)
class StoryContext:
    """What the judge sees of a story: its summary, when it has one, and a few members."""

    headline: str | None
    bullets: tuple[str, ...]
    members: tuple[PromptArticle, ...]


Judge = Callable[[PromptArticle, StoryContext], bool]


@dataclass(frozen=True)
class Candidate:
    story_id: int
    nearest_article_id: int
    similarity: float
    story_similarity: float


@dataclass(frozen=True)
class Assignment:
    story_id: int | None
    method: str
    similarity: float | None
    nearest_article_id: int | None
    story_similarity: float | None = None


@dataclass(frozen=True)
class MergeCandidate:
    keep_story_id: int
    drop_story_id: int
    similarity: float


@dataclass(frozen=True)
class _Entry:
    article_id: int
    story_id: int
    title: str
    summary: str | None
    published_at: datetime
    is_seed: bool
    vector: np.ndarray


def _normalize(vec: np.ndarray) -> np.ndarray:
    norm = np.linalg.norm(vec)
    if norm == 0:
        return vec
    return vec / norm


def _seed() -> Assignment:
    return Assignment(
        story_id=None,
        method=SEED,
        similarity=None,
        nearest_article_id=None,
    )


class NeighborIndex:
    def __init__(self) -> None:
        self._entries: list[_Entry] = []
        self._sums: dict[int, np.ndarray] = {}
        self._briefs: dict[int, tuple[str, tuple[str, ...]]] = {}

    def add(
        self,
        article_id: int,
        story_id: int,
        embedding: Sequence[float],
        *,
        title: str = "",
        summary: str | None = None,
        published_at: datetime | None = None,
        is_seed: bool = False,
    ) -> None:
        entry = _Entry(
            article_id=article_id,
            story_id=story_id,
            title=title,
            summary=summary,
            published_at=published_at if published_at is not None else _EPOCH,
            is_seed=is_seed,
            vector=_normalize(np.asarray(embedding, dtype=np.float64)),
        )
        self._entries.append(entry)
        self._sums[story_id] = self._sums.get(story_id, 0) + entry.vector

    def set_brief(self, story_id: int, headline: str, bullets: Sequence[str]) -> None:
        self._briefs[story_id] = (headline, tuple(bullets))

    def size(self, story_id: int) -> int:
        return sum(1 for entry in self._entries if entry.story_id == story_id)

    def candidates(self, embedding: Sequence[float]) -> list[Candidate]:
        """One candidate per story, closest to the story centroid first."""
        if not self._entries:
            return []
        query = _normalize(np.asarray(embedding, dtype=np.float64))
        similarities = np.stack([entry.vector for entry in self._entries]) @ query
        nearest: dict[int, tuple[float, int]] = {}
        for entry, similarity in zip(self._entries, similarities):
            best = nearest.get(entry.story_id)
            if best is None or similarity > best[0]:
                nearest[entry.story_id] = (float(similarity), entry.article_id)
        found = [
            Candidate(
                story_id=story_id,
                nearest_article_id=article_id,
                similarity=similarity,
                story_similarity=float(_normalize(self._sums[story_id]) @ query),
            )
            for story_id, (similarity, article_id) in nearest.items()
        ]
        return sorted(found, key=lambda candidate: candidate.story_similarity, reverse=True)

    def prompt_members(
        self, story_id: int, nearest_article_id: int | None, limit: int = _PROMPT_MEMBERS
    ) -> list[PromptArticle]:
        members = [entry for entry in self._entries if entry.story_id == story_id]
        chosen: list[_Entry] = []

        def take(entry: _Entry | None) -> None:
            if entry is None or len(chosen) >= limit:
                return
            if any(entry.article_id == picked.article_id for picked in chosen):
                return
            chosen.append(entry)

        by_id = {entry.article_id: entry for entry in members}
        if nearest_article_id is not None:
            take(by_id.get(nearest_article_id))
        seeds = [entry for entry in members if entry.is_seed]
        take(min(seeds, key=lambda entry: entry.published_at, default=None))
        take(max(members, key=lambda entry: entry.published_at, default=None))
        for entry in sorted(members, key=lambda entry: entry.published_at, reverse=True):
            take(entry)
        return [
            PromptArticle(
                title=entry.title,
                summary=entry.summary,
                published_at=None if entry.published_at == _EPOCH else entry.published_at,
            )
            for entry in chosen
        ]

    def story_context(self, story_id: int, nearest_article_id: int | None = None) -> StoryContext:
        brief = self._briefs.get(story_id)
        limit = _PROMPT_MEMBERS_WITH_BRIEF if brief else _PROMPT_MEMBERS
        members = tuple(self.prompt_members(story_id, nearest_article_id, limit=limit))
        if brief is None:
            return StoryContext(headline=None, bullets=(), members=members)
        return StoryContext(headline=brief[0], bullets=brief[1], members=members)

    def merge_candidates(
        self, changed: set[int], threshold: float = MERGE_THRESHOLD
    ) -> list[MergeCandidate]:
        """Story pairs with close centroids, at least one of them changed this run.

        Every story in the index has an article inside the window, so their time
        ranges overlap. The larger story is kept; on a tie, the older one.
        Closest pairs come first.
        """
        story_ids = sorted(self._sums)
        if len(story_ids) < 2 or not changed:
            return []
        centroids = np.stack([_normalize(self._sums[story_id]) for story_id in story_ids])
        similarities = centroids @ centroids.T
        sizes = {story_id: self.size(story_id) for story_id in story_ids}
        pairs: list[MergeCandidate] = []
        for i, first in enumerate(story_ids):
            for j in range(i + 1, len(story_ids)):
                second = story_ids[j]
                if first not in changed and second not in changed:
                    continue
                similarity = float(similarities[i, j])
                if similarity < threshold:
                    continue
                keep, drop = sorted((first, second), key=lambda story: (-sizes[story], story))
                pairs.append(MergeCandidate(keep, drop, similarity))
        return sorted(pairs, key=lambda pair: pair.similarity, reverse=True)

    def move(self, from_story_id: int, to_story_id: int) -> None:
        """Relabel every member of one story as a member of another."""
        self._entries = [
            replace(entry, story_id=to_story_id, is_seed=False)
            if entry.story_id == from_story_id
            else entry
            for entry in self._entries
        ]
        moved = self._sums.pop(from_story_id, None)
        if moved is not None:
            self._sums[to_story_id] = self._sums.get(to_story_id, 0) + moved
        self._briefs.pop(from_story_id, None)


def decide(
    embedding: Sequence[float],
    index: NeighborIndex,
    *,
    threshold: float = JOIN_THRESHOLD,
    story_threshold: float = STORY_THRESHOLD,
    floor: float = LLM_FLOOR,
    title: str = "",
    summary: str | None = None,
    published_at: datetime | None = None,
    judge: Judge | None = None,
) -> Assignment:
    candidates = [
        candidate for candidate in index.candidates(embedding) if candidate.similarity >= floor
    ]
    if not candidates:
        return _seed()
    for candidate in candidates:
        if candidate.similarity >= threshold and candidate.story_similarity >= story_threshold:
            return _join(candidate, COSINE)
    if judge is None:
        return _seed()
    best = candidates[0]
    article = PromptArticle(title=title, summary=summary, published_at=published_at)
    try:
        same = judge(article, index.story_context(best.story_id, best.nearest_article_id))
    except Exception:
        logger.warning("Same-happening judge failed; seeding", exc_info=True)
        return _seed()
    if not same:
        return _seed()
    return _join(best, LLM)


def _join(candidate: Candidate, method: str) -> Assignment:
    return Assignment(
        story_id=candidate.story_id,
        method=method,
        similarity=candidate.similarity,
        nearest_article_id=candidate.nearest_article_id,
        story_similarity=candidate.story_similarity,
    )

"""Assignment: an article joins the story it matches, or seeds a new one.

A story is scored as a whole, not by its single closest article. The nearest
member must be close (``JOIN_THRESHOLD``) and the article must also be close
to the story's centroid (``STORY_THRESHOLD``). Matching one member is not
enough, so a story cannot drift link by link: A pulls in B, B pulls in C,
until C has nothing to do with A. Articles that match a member but not the
story's core go to the judge, which picks among the few stories closest to the article.

A story is one event, so it has a lifespan: it takes articles published within
``STORY_SPAN`` of its first one. Later coverage starts a new story. Without
that, a story about a vote keeps absorbing the campaign before it and the
commentary after it, and grows for weeks.
"""

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone

import numpy as np

JOIN_THRESHOLD = 0.75
# Cosine to the story centroid. On the dev data every existing cosine join
# scores >= 0.756 and the nearest other story of a seed is <= 0.76.
STORY_THRESHOLD = 0.70
LLM_FLOOR = 0.55
# Centroid cosine a judged join needs, by the judge's answer. On a replay of
# the referendum week most "development" joins below 0.70 and "same_event"
# joins below 0.62 were wrong: inflation figures into a gold-price story, a
# criminal case into referendum commentary.
SAME_EVENT_FLOOR = 0.62
DEVELOPMENT_FLOOR = 0.70
# How many stories the judge chooses among. The closest by centroid is often
# a near-tie with the right one.
JUDGE_CANDIDATES = 3
# Pair score above which two stories go to the merge judge. See merge_candidates.
MERGE_THRESHOLD = 0.80
# Members of the larger story compared with the smaller story's centroid.
_MERGE_TOP_MEMBERS = 3
# Pairs with centroids further apart than this are not scored at all.
_MERGE_PREFILTER = 0.65
# How long after its first article a story still takes new ones. In production
# half the articles of 50+ article stories arrived over five days after the
# first, most of them follow-ups and commentary on an event long over.
STORY_SPAN = timedelta(days=3)
SEED = "seed"
COSINE = "cosine"
LLM = "llm"

SAME_EVENT = "same_event"
DEVELOPMENT = "development"
RELATED_TOPIC = "related_topic"
DIFFERENT = "different"
RELATIONS = (SAME_EVENT, DEVELOPMENT, RELATED_TOPIC, DIFFERENT)
JOIN_RELATIONS = frozenset({SAME_EVENT, DEVELOPMENT})

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


@dataclass(frozen=True)
class Verdict:
    """The judge's pick: ``story`` indexes the candidates it was shown, None for none."""

    story: int | None
    relation: str


# None means the judge is unavailable (no API key); the article seeds.
Judge = Callable[[PromptArticle, Sequence[StoryContext]], Verdict | None]


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
    # The judge's answer, when it was asked.
    relation: str | None = None


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


def _seed(relation: str | None = None) -> Assignment:
    return Assignment(
        story_id=None,
        method=SEED,
        similarity=None,
        nearest_article_id=None,
        relation=relation,
    )


class NeighborIndex:
    def __init__(self) -> None:
        self._entries: list[_Entry] = []
        self._sums: dict[int, np.ndarray] = {}
        self._briefs: dict[int, tuple[str, tuple[str, ...]]] = {}
        # Earliest known article of each story, including members outside the window.
        self._started: dict[int, datetime] = {}

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
        if published_at is not None:
            self.set_started(story_id, published_at)

    def set_started(self, story_id: int, at: datetime) -> None:
        """Record a story's first article when it is older than the loaded members."""
        known = self._started.get(story_id)
        self._started[story_id] = at if known is None else min(known, at)

    def is_open(self, story_id: int, at: datetime | None) -> bool:
        """Whether the story still takes an article published at ``at``."""
        started = self._started.get(story_id)
        # Read at call time so the replay harness can try other spans.
        return at is None or started is None or at - started <= STORY_SPAN

    def set_brief(self, story_id: int, headline: str, bullets: Sequence[str]) -> None:
        self._briefs[story_id] = (headline, tuple(bullets))

    def size(self, story_id: int) -> int:
        return sum(1 for entry in self._entries if entry.story_id == story_id)

    def candidates(
        self, embedding: Sequence[float], at: datetime | None = None
    ) -> list[Candidate]:
        """One candidate per story still open at ``at``, closest to the centroid first."""
        if not self._entries:
            return []
        query = _normalize(np.asarray(embedding, dtype=np.float64))
        similarities = np.stack([entry.vector for entry in self._entries]) @ query
        nearest: dict[int, tuple[float, int]] = {}
        for entry, similarity in zip(self._entries, similarities):
            if not self.is_open(entry.story_id, at):
                continue
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
        self,
        changed: set[int],
        threshold: float = MERGE_THRESHOLD,
        *,
        at: datetime | None = None,
    ) -> list[MergeCandidate]:
        """Story pairs that look like one story, at least one of them changed this run.

        A pair scores the higher of its centroid cosine and the mean cosine of
        the smaller story's centroid to the larger story's closest members. A
        big story's centroid is a blur of all its developments, so a duplicate
        of one development matches its members, not its centroid.

        Every story in the index has an article inside the window, so their time
        ranges overlap. Stories closed at ``at`` take no merges, the same as
        they take no articles. The larger story is kept; on a tie, the older
        one. Closest pairs come first.
        """
        story_ids = sorted(s for s in self._sums if self.is_open(s, at))
        if len(story_ids) < 2 or not changed:
            return []
        position = {story_id: i for i, story_id in enumerate(story_ids)}
        centroids = np.stack([_normalize(self._sums[story_id]) for story_id in story_ids])
        similarities = centroids @ centroids.T
        entries = [entry for entry in self._entries if entry.story_id in position]
        vectors = np.stack([entry.vector for entry in entries])
        owners = np.array([position[entry.story_id] for entry in entries])
        sizes = np.bincount(owners, minlength=len(story_ids))
        pairs: list[MergeCandidate] = []
        seen: set[tuple[int, int]] = set()
        for story_id in sorted(changed & set(position)):
            i = position[story_id]
            # Row: each story's centroid against this story's members, and this
            # story's centroid against every member.
            against_mine = centroids @ vectors[owners == i].T
            mine_against = vectors @ centroids[i]
            for j in np.flatnonzero(similarities[i] >= _MERGE_PREFILTER):
                if j == i:
                    continue
                keep, drop = sorted((i, int(j)), key=lambda k: (-sizes[k], story_ids[k]))
                if (keep, drop) in seen:
                    continue
                if keep == i:
                    members = against_mine[drop]
                else:
                    members = mine_against[owners == keep]
                top = np.sort(members)[-_MERGE_TOP_MEMBERS:]
                score = max(float(similarities[i, j]), float(top.mean()))
                if score < threshold:
                    continue
                seen.add((keep, drop))
                pairs.append(MergeCandidate(story_ids[keep], story_ids[drop], score))
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
        started = self._started.pop(from_story_id, None)
        if started is not None:
            self.set_started(to_story_id, started)


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
        candidate
        for candidate in index.candidates(embedding, published_at)
        if candidate.similarity >= floor
    ]
    if not candidates:
        return _seed()
    for candidate in candidates:
        if candidate.similarity >= threshold and candidate.story_similarity >= story_threshold:
            return _join(candidate, COSINE)
    if judge is None:
        return _seed()
    shown = candidates[:JUDGE_CANDIDATES]
    article = PromptArticle(title=title, summary=summary, published_at=published_at)
    try:
        verdict = judge(
            article,
            [index.story_context(c.story_id, c.nearest_article_id) for c in shown],
        )
    except Exception:
        logger.warning("Same-happening judge failed; seeding", exc_info=True)
        return _seed()
    if verdict is None:
        return _seed()
    if verdict.story is None or verdict.relation not in JOIN_RELATIONS:
        return _seed(verdict.relation)
    chosen = shown[verdict.story]
    floor_for_relation = SAME_EVENT_FLOOR if verdict.relation == SAME_EVENT else DEVELOPMENT_FLOOR
    if chosen.story_similarity < floor_for_relation:
        return _seed(verdict.relation)
    return _join(chosen, LLM, verdict.relation)


def _join(candidate: Candidate, method: str, relation: str | None = None) -> Assignment:
    return Assignment(
        story_id=candidate.story_id,
        method=method,
        similarity=candidate.similarity,
        nearest_article_id=candidate.nearest_article_id,
        story_similarity=candidate.story_similarity,
        relation=relation,
    )

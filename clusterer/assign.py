import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone

import numpy as np

JOIN_THRESHOLD = 0.75
LLM_FLOOR = 0.55
SEED = "seed"
COSINE = "cosine"
LLM = "llm"

PromptMember = tuple[str, str | None]
Judge = Callable[[str, str | None, Sequence[PromptMember]], bool]

logger = logging.getLogger(__name__)
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


@dataclass(frozen=True)
class Neighbor:
    article_id: int
    story_id: int
    similarity: float


@dataclass(frozen=True)
class Assignment:
    story_id: int | None
    method: str
    similarity: float | None
    nearest_article_id: int | None


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
        self._entries.append(
            _Entry(
                article_id=article_id,
                story_id=story_id,
                title=title,
                summary=summary,
                published_at=published_at if published_at is not None else _EPOCH,
                is_seed=is_seed,
                vector=_normalize(np.asarray(embedding, dtype=np.float64)),
            )
        )

    def nearest(self, embedding: Sequence[float]) -> Neighbor | None:
        if not self._entries:
            return None
        query = _normalize(np.asarray(embedding, dtype=np.float64))
        similarities = np.stack([entry.vector for entry in self._entries]) @ query
        index = int(np.argmax(similarities))
        entry = self._entries[index]
        return Neighbor(
            article_id=entry.article_id,
            story_id=entry.story_id,
            similarity=float(similarities[index]),
        )

    def prompt_members(self, story_id: int, nearest_article_id: int) -> list[PromptMember]:
        members = [entry for entry in self._entries if entry.story_id == story_id]
        chosen: list[_Entry] = []

        def take(entry: _Entry | None) -> None:
            if entry is None or len(chosen) >= 4:
                return
            if any(entry.article_id == picked.article_id for picked in chosen):
                return
            chosen.append(entry)

        by_id = {entry.article_id: entry for entry in members}
        take(by_id.get(nearest_article_id))
        seeds = [entry for entry in members if entry.is_seed]
        take(min(seeds, key=lambda entry: entry.published_at, default=None))
        take(max(members, key=lambda entry: entry.published_at, default=None))
        for entry in sorted(members, key=lambda entry: entry.published_at, reverse=True):
            take(entry)
        return [(entry.title, entry.summary) for entry in chosen]


def decide(
    embedding: Sequence[float],
    index: NeighborIndex,
    *,
    threshold: float = JOIN_THRESHOLD,
    floor: float = LLM_FLOOR,
    title: str = "",
    summary: str | None = None,
    judge: Judge | None = None,
) -> Assignment:
    neighbor = index.nearest(embedding)
    if neighbor is None or neighbor.similarity < floor:
        return _seed()
    if neighbor.similarity >= threshold:
        return Assignment(
            story_id=neighbor.story_id,
            method=COSINE,
            similarity=neighbor.similarity,
            nearest_article_id=neighbor.article_id,
        )
    if judge is None:
        return _seed()
    try:
        same = judge(title, summary, index.prompt_members(neighbor.story_id, neighbor.article_id))
    except Exception:
        logger.warning("Same-happening judge failed; seeding", exc_info=True)
        return _seed()
    if not same:
        return _seed()
    return Assignment(
        story_id=neighbor.story_id,
        method=LLM,
        similarity=neighbor.similarity,
        nearest_article_id=neighbor.article_id,
    )

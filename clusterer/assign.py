from dataclasses import dataclass
from collections.abc import Sequence

import numpy as np

JOIN_THRESHOLD = 0.75
SEED = "seed"
COSINE = "cosine"


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


def _normalize(vec: np.ndarray) -> np.ndarray:
    norm = np.linalg.norm(vec)
    if norm == 0:
        return vec
    return vec / norm


class NeighborIndex:
    def __init__(self) -> None:
        self._article_ids: list[int] = []
        self._story_ids: list[int] = []
        self._vectors: list[np.ndarray] = []

    def add(self, article_id: int, story_id: int, embedding: Sequence[float]) -> None:
        self._article_ids.append(article_id)
        self._story_ids.append(story_id)
        self._vectors.append(_normalize(np.asarray(embedding, dtype=np.float64)))

    def nearest(self, embedding: Sequence[float]) -> Neighbor | None:
        if not self._vectors:
            return None
        query = _normalize(np.asarray(embedding, dtype=np.float64))
        similarities = np.stack(self._vectors) @ query
        index = int(np.argmax(similarities))
        return Neighbor(
            article_id=self._article_ids[index],
            story_id=self._story_ids[index],
            similarity=float(similarities[index]),
        )


def decide(
    embedding: Sequence[float],
    index: NeighborIndex,
    *,
    threshold: float = JOIN_THRESHOLD,
) -> Assignment:
    neighbor = index.nearest(embedding)
    if neighbor is None or neighbor.similarity < threshold:
        return Assignment(
            story_id=None,
            method=SEED,
            similarity=None,
            nearest_article_id=None,
        )
    return Assignment(
        story_id=neighbor.story_id,
        method=COSINE,
        similarity=neighbor.similarity,
        nearest_article_id=neighbor.article_id,
    )

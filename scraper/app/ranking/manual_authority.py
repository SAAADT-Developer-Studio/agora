"""Adapt the existing manual publisher tiers to normalized authority values."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from app.providers.ranks import get_rank_map


def normalize_manual_authority(rank: int | None) -> float | None:
    """Map fixed tiers 0..4 (best to worst) to authority 1..0; missing stays missing."""
    if rank is None:
        return None
    if isinstance(rank, bool) or not isinstance(rank, int) or not 0 <= rank <= 4:
        raise ValueError("manual authority rank must be an integer from 0 to 4, or None")
    return 1.0 - rank / 4.0


@dataclass(frozen=True)
class ManualAuthorityProvider:
    """Immutable snapshot of existing manual ranks, or explicitly supplied ranks.

    Supplied mappings may also come from already-loaded NewsProvider.rank values.
    The fixed scale never depends on which publishers are in the current event.
    """

    ranks: Mapping[str, int | None] = field(default_factory=get_rank_map)

    def __post_init__(self) -> None:
        canonical = {}
        for key, rank in self.ranks.items():
            if not isinstance(key, str) or not key.strip():
                raise ValueError("publisher keys must be non-empty strings")
            publisher = key.strip().casefold()
            if publisher in canonical:
                raise ValueError(f"duplicate publisher key: {publisher}")
            normalize_manual_authority(rank)
            canonical[publisher] = rank
        object.__setattr__(self, "ranks", MappingProxyType(canonical))

    def get_authority(self, publisher_key: str) -> float | None:
        return normalize_manual_authority(self.ranks.get(publisher_key.strip().casefold()))

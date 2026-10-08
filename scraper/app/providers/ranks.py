from __future__ import annotations

from typing import TYPE_CHECKING

from app.providers.enums import ProviderKey

if TYPE_CHECKING:
    from app.providers.news_provider import NewsProvider

RANKS: dict[int, list[ProviderKey]] = {
    0: [
        ProviderKey._24UR,
        ProviderKey.SIOL,
        ProviderKey.ZURNAL24,
        ProviderKey.SVET24,
        ProviderKey.RTV,
        ProviderKey.SLOVENSKENOVICE,
    ],
    1: [
        ProviderKey.DELO,
        ProviderKey.DNEVNIK,
        ProviderKey.N1INFO,
        ProviderKey.VECER,
        ProviderKey.MARIBOR24,
    ],
    2: [
        ProviderKey.LOKALEC,
        ProviderKey.REPORTER,
        ProviderKey.STA,
        ProviderKey.NECENZURIRANO,
        ProviderKey.NOVA24TV,
        ProviderKey.DEMOKRACIJA,
        ProviderKey.DOMOVINA,
        ProviderKey.CEKIN,
        ProviderKey.INFO360,
    ],
    3: [
        ProviderKey.BLOOMBERGADRIA,
        ProviderKey.FINANCE,
        ProviderKey.ZANIMAME,
        ProviderKey.LJUBLJANSKENOVICE,
        ProviderKey.PRIMORSKENOVICE,
    ],
    4: [
        ProviderKey.MLADINA,
        ProviderKey.SLOTECH,
    ],
}


def get_rank_map() -> dict[str, int]:
    """Return the manual tiers without initializing providers or application config."""
    rank_map: dict[str, int] = {}
    for rank, keys in RANKS.items():
        for key in keys:
            if key.value in rank_map:
                raise ValueError(f"Duplicate provider key found: {key}")
            rank_map[key.value] = rank
    return rank_map


def assign_ranks(providers: list[NewsProvider]) -> None:
    rank_map = get_rank_map()

    for provider in providers:
        provider.rank = rank_map[provider.key]

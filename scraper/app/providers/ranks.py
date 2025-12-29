from app.providers.enums import ProviderKey
from app.providers.providers import NewsProvider

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
        ProviderKey.ZANIMAME,
        ProviderKey.LJUBLJANSKENOVICE,
        ProviderKey.PRIMORSKENOVICE,
    ],
    4: [
        ProviderKey.MLADINA,
        ProviderKey.SLOTECH,
    ],
}


def assign_ranks(providers: list[NewsProvider]) -> None:
    rank_map = {}
    for rank, keys in RANKS.items():
        for key in keys:
            if key in rank_map:
                raise ValueError(f"Duplicate provider key found: {key}")
            rank_map[key.value] = rank

    for provider in providers:
        provider.rank = rank_map[provider.key]

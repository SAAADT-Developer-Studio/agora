"""Database-independent contract for the cluster-ranking engine.

Ranking implementations must be pure: the same cluster, evaluation time, and
configuration must produce the same result. Database loading and persistence
belong outside this module.
"""

from datetime import datetime
from typing import Protocol

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    model_validator,
)


class ContractModel(BaseModel):
    """Strict and immutable base model for ranking contracts."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
        allow_inf_nan=False,
    )


class RankableArticle(ContractModel):
    """Article data available to a ranking implementation.

    Optional fields make the contract usable before every future ranking
    signal is implemented. A scorer must define explicit fallbacks for missing
    values instead of interpreting them as the best or worst possible value.
    """

    article_id: int = Field(gt=0)
    publisher_key: str = Field(min_length=1)
    title: str = Field(min_length=1)
    published_at: AwareDatetime
    first_seen_at: AwareDatetime | None = None
    summary: str | None = None
    content: str | None = None
    categories: tuple[str, ...] = ()
    llm_rank: int | None = Field(default=None, ge=1, le=10)
    embedding: tuple[float, ...] = ()
    publisher_authority_score: float | None = Field(default=None, ge=0.0, le=1.0)
    cluster_membership_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    originality_score: float | None = Field(default=None, ge=0.0, le=1.0)
    is_syndicated: bool | None = None
    is_primary_source: bool | None = None


class ClusterNewsworthiness(ContractModel):
    """Precomputed cluster evaluation, prepared outside the pure ranking engine.

    The producer normalizes its value to [0, 1] and records when the evaluation
    became available. This can later carry a cluster-level LLM judgment without
    changing the ranking function or its component output contract.
    """

    score: float = Field(ge=0.0, le=1.0, strict=True)
    evaluated_at: AwareDatetime
    version: str = Field(min_length=1)


class RankableCluster(ContractModel):
    """Snapshot of one cluster supplied to the ranking function."""

    cluster_id: int = Field(gt=0)
    articles: tuple[RankableArticle, ...] = Field(min_length=1)
    category: str | None = None
    created_at: AwareDatetime | None = None
    changed_at: AwareDatetime | None = None
    newsworthiness: ClusterNewsworthiness | None = None

    @model_validator(mode="after")
    def article_ids_must_be_unique(self) -> "RankableCluster":
        article_ids = [article.article_id for article in self.articles]
        if len(article_ids) != len(set(article_ids)):
            raise ValueError("article IDs must be unique within a rankable cluster")
        return self


class RankingConfig(ContractModel):
    """Versioned configuration passed into a ranking implementation.

    Parameters intentionally remain JSON-compatible so later tickets can add
    weights, half-lives, caps, and thresholds without changing the function
    signature.
    """

    version: str = Field(min_length=1)
    parameters: dict[str, JsonValue] = Field(default_factory=dict)


class RankingComponentScores(ContractModel):
    """Normalized, higher-is-better component scores."""

    coverage_score: float = Field(ge=0.0, le=1.0)
    momentum_score: float = Field(ge=0.0, le=1.0)
    freshness_score: float = Field(ge=0.0, le=1.0)
    article_contribution_score: float = Field(ge=0.0, le=1.0)
    publisher_authority_score: float = Field(ge=0.0, le=1.0)
    semantic_importance_score: float = Field(ge=0.0, le=1.0)
    cluster_confidence_score: float = Field(ge=0.0, le=1.0)


class RankingResult(ContractModel):
    """Complete, persistable output of a cluster-ranking calculation."""

    cluster_id: int = Field(gt=0)
    score: float = Field(ge=0.0, le=1.0)
    components: RankingComponentScores
    config_version: str = Field(min_length=1)
    evaluated_at: AwareDatetime


class PublisherAuthorityProvider(Protocol):
    """Source-independent interface used when preparing a ranking snapshot.

    Return a normalized higher-is-better score in [0, 1], or None when unknown.
    Fetching or calculating authority belongs outside the ranking function;
    ranking consumes only the resulting RankableArticle authority values.
    """

    def get_authority(self, publisher_key: str) -> float | None: ...


class RankingFunction(Protocol):
    """Callable interface implemented by every cluster-ranking formula.

    Implementations must not perform I/O or normalize against other clusters.
    This guarantees that changing one cluster cannot change another cluster's
    score.
    """

    def __call__(
        self,
        cluster: RankableCluster,
        evaluated_at: datetime,
        config: RankingConfig,
    ) -> RankingResult: ...

"""Detect substantially shared writing within one event snapshot."""

from datetime import datetime, timezone
import re
from typing import Literal
import unicodedata

from pydantic import AwareDatetime, Field, model_validator

from app.ranking.contracts import ContractModel, RankableCluster, RankingConfig


ALGORITHM_VERSION = "syndication-v1"
SyndicationStatus = Literal["independently_written", "syndicated_duplicated", "unknown"]


class SyndicationConfig(ContractModel):
    """Conservative initial thresholds for comparing extracted article bodies."""

    minimum_content_tokens: int = Field(default=50, ge=5)
    minimum_unique_shingles: int = Field(default=20, ge=1)
    similarity_threshold: float = Field(default=0.80, gt=0.0, le=1.0)


class ArticleSyndication(ContractModel):
    article_id: int = Field(gt=0)
    status: SyndicationStatus
    family_id: str | None = None
    representative_article_id: int | None = Field(default=None, gt=0)
    max_text_similarity: float | None = Field(default=None, ge=0.0, le=1.0)
    originality_score: float | None = Field(default=None, ge=0.0, le=1.0)
    reason: Literal[
        "matching_content", "no_matching_content", "content_unavailable",
        "insufficient_content", "insufficient_distinct_content",
    ]


class SyndicatedFamily(ContractModel):
    family_id: str
    representative_article_id: int = Field(gt=0)
    article_ids: tuple[int, ...] = Field(min_length=2)
    minimum_text_similarity: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def validate_members(self) -> "SyndicatedFamily":
        if len(self.article_ids) != len(set(self.article_ids)):
            raise ValueError("family article IDs must be unique")
        if self.representative_article_id != self.article_ids[0]:
            raise ValueError("the first family member must be its representative")
        return self


class SyndicationResult(ContractModel):
    cluster_id: int = Field(gt=0)
    articles: tuple[ArticleSyndication, ...]
    families: tuple[SyndicatedFamily, ...]
    excluded_article_ids: tuple[int, ...]
    config_version: str
    algorithm_version: str = ALGORITHM_VERSION
    evaluated_at: AwareDatetime


def detect_syndication(
    cluster: RankableCluster,
    evaluated_at: datetime,
    config: RankingConfig,
) -> SyndicationResult:
    """Classify body-text reuse; titles, summaries, embeddings and flags aren't proof.

    Every member of a shared-writing family is marked syndicated/duplicated.
    Its earliest observed member represents the family for scoring, without
    claiming that publisher was the actual author. Independent means no matching
    family in this snapshot, not verified originality across the wider web.
    """
    if evaluated_at.tzinfo is None or evaluated_at.utcoffset() is None:
        raise ValueError("evaluated_at must have a timezone")
    evaluated_at = evaluated_at.astimezone(timezone.utc)
    policy = SyndicationConfig.model_validate(config.parameters.get("syndication", {}))
    eligible = sorted(
        (article for article in cluster.articles
         if article.published_at <= evaluated_at
         and (article.first_seen_at is None or article.first_seen_at <= evaluated_at)),
        key=lambda article: (
            article.published_at.astimezone(timezone.utc),
            (article.first_seen_at or article.published_at).astimezone(timezone.utc),
            article.article_id,
        ),
    )
    shingles: dict[int, frozenset[tuple[str, ...]]] = {}
    unknown: dict[int, str] = {}
    for article in eligible:
        tokens = tuple(re.findall(r"\w+", unicodedata.normalize(
            "NFKC", article.content or "").casefold()))
        if not tokens:
            unknown[article.article_id] = "content_unavailable"
        elif len(tokens) < policy.minimum_content_tokens:
            unknown[article.article_id] = "insufficient_content"
        else:
            body = frozenset(tokens[index:index + 5] for index in range(len(tokens) - 4))
            if len(body) < policy.minimum_unique_shingles:
                unknown[article.article_id] = "insufficient_distinct_content"
            else:
                shingles[article.article_id] = body

    # Symmetric coverage requires most of BOTH bodies to match. A shared quote
    # or an excerpt from a much longer, otherwise distinct report is insufficient.
    similarities: dict[tuple[int, int], float] = {}
    maximum: dict[int, float] = {}
    prior_reuse: dict[int, float] = {}
    groups: list[list[int]] = []
    for article_id, body in shingles.items():
        for earlier_id, earlier_body in shingles.items():
            if earlier_id == article_id:
                break
            shared = len(body & earlier_body)
            similarity = shared / max(len(body), len(earlier_body))
            prior_reuse[article_id] = max(
                prior_reuse.get(article_id, 0.0), shared / len(body)
            )
            similarities[article_id, earlier_id] = similarity
            maximum[article_id] = max(maximum.get(article_id, 0.0), similarity)
            maximum[earlier_id] = max(maximum.get(earlier_id, 0.0), similarity)

        # Require a match with EVERY member, avoiding A≈B≈C chains that collapse
        # A and C even when their written content differs substantially.
        candidates = [
            (min(similarities[article_id, member] for member in members), index)
            for index, members in enumerate(groups)
        ]
        best = max(candidates, key=lambda candidate: (candidate[0], -candidate[1]), default=None)
        if best is not None and best[0] >= policy.similarity_threshold:
            groups[best[1]].append(article_id)
        else:
            groups.append([article_id])

    families = []
    membership: dict[int, SyndicatedFamily] = {}
    for members in groups:
        if len(members) < 2:
            continue
        family = SyndicatedFamily(
            family_id=f"{cluster.cluster_id}:{members[0]}",
            representative_article_id=members[0],
            article_ids=tuple(members),
            minimum_text_similarity=min(
                similarities[member, earlier]
                for index, member in enumerate(members) for earlier in members[:index]
            ),
        )
        families.append(family)
        membership.update((member, family) for member in members)

    outcomes = []
    for article in eligible:
        family = membership.get(article.article_id)
        reason = unknown.get(article.article_id)
        outcomes.append(ArticleSyndication(
            article_id=article.article_id,
            status=("unknown" if reason else
                    "syndicated_duplicated" if family else "independently_written"),
            family_id=family.family_id if family else None,
            representative_article_id=family.representative_article_id if family else None,
            max_text_similarity=maximum.get(article.article_id),
            originality_score=None if reason else 1.0 - prior_reuse.get(article.article_id, 0.0),
            reason=reason or ("matching_content" if family else "no_matching_content"),
        ))
    included = {article.article_id for article in eligible}
    return SyndicationResult(
        cluster_id=cluster.cluster_id, articles=tuple(outcomes), families=tuple(families),
        excluded_article_ids=tuple(sorted(
            article.article_id for article in cluster.articles if article.article_id not in included
        )),
        config_version=config.version, evaluated_at=evaluated_at,
    )

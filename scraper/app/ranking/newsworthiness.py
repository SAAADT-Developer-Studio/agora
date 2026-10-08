"""Aggregate article LLM importance into duplicate-adjusted event newsworthiness."""

from datetime import datetime, timezone
from math import fsum
from typing import Literal

from pydantic import AwareDatetime, Field

from app.ranking.contracts import ContractModel, RankableCluster, RankingConfig
from app.ranking.syndication import detect_syndication


ALGORITHM_VERSION = "newsworthiness-v1"


class NewsworthinessConfig(ContractModel):
    """Initial policy: strongest report blended with a few distinct reports."""

    top_reports: int = Field(default=3, ge=1, strict=True)
    strongest_weight: float = Field(default=0.5, ge=0.0, le=1.0)
    unknown_importance: float = Field(default=0.5, ge=0.0, le=1.0)
    cluster_score_weight: float = Field(default=1.0, ge=0.0, le=1.0)


class NewsworthinessReport(ContractModel):
    """One reporting unit: a standalone article or a collapsed syndicated family."""

    representative_article_id: int = Field(gt=0)
    publisher_key: str = Field(min_length=1)
    article_ids: tuple[int, ...] = Field(min_length=1)
    syndication_family_id: str | None = None
    basis: Literal["independent", "family_representative", "unknown", "unmatched_syndication"]
    score_article_id: int | None = Field(default=None, gt=0)
    llm_rank: int | None = Field(default=None, ge=1, le=10)
    importance_score: float | None = Field(default=None, ge=0.0, le=1.0)
    used_family_score_fallback: bool
    selected: bool = False
    selection_reason: Literal[
        "selected", "missing_importance", "same_publisher", "outside_top_reports",
        "unverified_reporting",
    ]


class NewsworthinessResult(ContractModel):
    cluster_id: int = Field(gt=0)
    semantic_importance_score: float = Field(ge=0.0, le=1.0)
    source: Literal["article_ranks", "cluster_evaluation", "blended", "fallback", "unavailable"]
    article_newsworthiness_score: float = Field(ge=0.0, le=1.0)
    article_basis: Literal["independent_reports", "unverified_report", "missing_scores", "no_eligible_articles"]
    strongest_article_score: float | None = Field(default=None, ge=0.0, le=1.0)
    top_reports_mean: float | None = Field(default=None, ge=0.0, le=1.0)
    selected_article_ids: tuple[int, ...]
    reports: tuple[NewsworthinessReport, ...]
    cluster_evaluation_status: Literal["absent", "future", "disabled", "no_eligible_articles", "used"]
    applied_cluster_weight: float = Field(ge=0.0, le=1.0)
    cluster_evaluation_score: float | None = Field(default=None, ge=0.0, le=1.0)
    cluster_evaluation_version: str | None = None
    excluded_article_ids: tuple[int, ...]
    config_version: str
    algorithm_version: str = ALGORITHM_VERSION
    syndication_algorithm_version: str
    evaluated_at: AwareDatetime


def normalize_llm_importance(rank: int | None) -> float | None:
    """Map existing higher-is-better ranks 1..10 to 0..1; None remains unknown."""
    if rank is None:
        return None
    if isinstance(rank, bool) or not isinstance(rank, int) or not 1 <= rank <= 10:
        raise ValueError("LLM importance must be an integer from 1 to 10 or None")
    return (rank - 1) / 9.0


def score_newsworthiness(
    cluster: RankableCluster, evaluated_at: datetime, config: RankingConfig,
) -> NewsworthinessResult:
    """Return the engine's semantic-importance component without I/O or count bonuses.

    Keep one score per written family and at most one report per publisher in
    the top set. Unknown reporting is an explicit single-report fallback only.
    An optional precomputed cluster evaluation can replace or supplement article
    aggregation through the same function signature and normalized output.
    """
    policy = NewsworthinessConfig.model_validate(config.parameters.get("newsworthiness", {}))
    detection = detect_syndication(cluster, evaluated_at, config)
    evaluated_at = detection.evaluated_at
    articles = {article.article_id: article for article in cluster.articles}
    families = {family.family_id: family for family in detection.families}
    reports = []
    for outcome in detection.articles:
        family = families.get(outcome.family_id)
        if family is not None and outcome.article_id != family.representative_article_id:
            continue
        representative = articles[outcome.article_id]
        article_ids = family.article_ids if family is not None else (outcome.article_id,)
        # Keep the representative's judgment even if copies have higher LLM
        # ranks. Only a missing rank permits using the first scored family member.
        scored = next((articles[article_id] for article_id in article_ids
                       if articles[article_id].llm_rank is not None), None)
        basis = ("family_representative" if family is not None else
                 "unmatched_syndication" if representative.is_syndicated is True else
                 "unknown" if outcome.status == "unknown" else "independent")
        rank = scored.llm_rank if scored is not None else None
        reports.append(NewsworthinessReport(
            representative_article_id=representative.article_id,
            publisher_key=representative.publisher_key.casefold(), article_ids=article_ids,
            syndication_family_id=outcome.family_id, basis=basis,
            score_article_id=scored.article_id if scored is not None else None,
            llm_rank=rank, importance_score=normalize_llm_importance(rank),
            used_family_score_fallback=scored is not None and scored.article_id != representative.article_id,
            selection_reason="missing_importance" if scored is None else "outside_top_reports",
        ))

    independent = [index for index, report in enumerate(reports)
                   if report.importance_score is not None
                   and report.basis in ("independent", "family_representative")]
    pool = independent or [index for index, report in enumerate(reports)
                           if report.importance_score is not None]
    if independent:
        article_basis = "independent_reports"
    elif pool:
        article_basis = "unverified_report"
    else:
        article_basis = "missing_scores" if detection.articles else "no_eligible_articles"
    pool.sort(key=lambda index: (
        -reports[index].importance_score,
        articles[reports[index].representative_article_id].published_at.astimezone(timezone.utc),
        (articles[reports[index].representative_article_id].first_seen_at
         or articles[reports[index].representative_article_id].published_at).astimezone(timezone.utc),
        reports[index].representative_article_id,
    ))
    # Unverified bodies cannot supply several purportedly independent votes.
    limit = policy.top_reports if independent else 1
    selected = []
    publishers = set()
    for index in pool:
        report = reports[index]
        if report.publisher_key in publishers:
            reason = "same_publisher"
        else:
            publishers.add(report.publisher_key)
            reason = "selected" if len(selected) < limit else "outside_top_reports"
        if reason == "selected":
            selected.append(index)
        reports[index] = report.model_copy(update={"selected": reason == "selected", "selection_reason": reason})
    if independent:
        reports = [report.model_copy(update={"selection_reason": "unverified_reporting"})
                   if report.importance_score is not None
                   and report.basis in ("unknown", "unmatched_syndication") else report
                   for report in reports]

    strongest = reports[selected[0]].importance_score if selected else None
    mean = fsum(reports[index].importance_score for index in selected) / len(selected) if selected else None
    article_score = (policy.strongest_weight * strongest + (1.0 - policy.strongest_weight) * mean
                     if selected else policy.unknown_importance if detection.articles else 0.0)
    score = article_score
    source = "article_ranks" if selected else "fallback" if detection.articles else "unavailable"
    evaluation = cluster.newsworthiness
    cluster_status = "absent"
    cluster_score = cluster_version = None
    cluster_weight = 0.0
    if evaluation is not None:
        if evaluation.evaluated_at > evaluated_at:
            cluster_status = "future"
        elif not detection.articles:
            cluster_status = "no_eligible_articles"
        elif policy.cluster_score_weight == 0:
            cluster_status = "disabled"
        else:
            cluster_status = "used"
            cluster_score, cluster_version = evaluation.score, evaluation.version
            # A real cluster judgment should not be diluted with an invented
            # article fallback when every usable article importance is missing.
            cluster_weight = policy.cluster_score_weight if selected else 1.0
            score = cluster_weight * cluster_score + (1.0 - cluster_weight) * article_score
            source = "cluster_evaluation" if cluster_weight == 1.0 else "blended"
    return NewsworthinessResult(
        cluster_id=cluster.cluster_id, semantic_importance_score=min(1.0, max(0.0, score)),
        source=source, article_newsworthiness_score=article_score, article_basis=article_basis,
        strongest_article_score=strongest, top_reports_mean=mean,
        selected_article_ids=tuple(reports[index].score_article_id for index in selected),
        reports=tuple(reports), cluster_evaluation_status=cluster_status,
        applied_cluster_weight=cluster_weight, cluster_evaluation_score=cluster_score,
        cluster_evaluation_version=cluster_version, excluded_article_ids=detection.excluded_article_ids,
        config_version=config.version, syndication_algorithm_version=detection.algorithm_version,
        evaluated_at=evaluated_at,
    )

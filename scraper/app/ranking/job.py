"""Score one clustering run and isolate a bad cluster from the rest of the batch."""

from datetime import datetime
import logging

from sqlalchemy.orm import object_session

from app.ranking import persistence
from app.ranking.contracts import RankingConfig
from database.repositories import ClusterV2Repository


def score_cluster(
    cluster, evaluated_at: datetime, config: RankingConfig, *,
    dry_run: bool = False, ranking_run_id: int | None = None,
) -> str:
    """Load, score, and persist one cluster. Return ``scored`` or ``skipped``.

    Validation failures (empty title, non-finite embedding, membership from
    another run) are logged and skipped. They do not abort the batch. A
    database error rolls back only this cluster's savepoint when the row is
    attached to a session.
    """
    session = object_session(cluster)

    def apply() -> str:
        if not cluster.memberships:
            logging.warning("Skipping empty cluster %s", cluster.id)
            return "skipped"
        # Look up through the module so a test can replace the scorer.
        persistence.rank_and_save_cluster(
            cluster, evaluated_at, config, dry_run=dry_run, ranking_run_id=ranking_run_id,
        )
        return "scored"

    try:
        if session is None:
            return apply()
        with session.begin_nested():
            return apply()
    except Exception as exc:
        logging.exception("Skipping cluster %s: %s", cluster.id, exc)
        return "skipped"


def expire_cluster(
    cluster, evaluated_at: datetime, *, cutoff: datetime, config: RankingConfig,
    ranking_run_id: int | None, dry_run: bool = False,
) -> str:
    """Zero one stale row. Return ``expired`` or ``skipped``."""
    session = object_session(cluster)

    def apply() -> str:
        if not dry_run:
            persistence.expire_cluster_ranking(
                cluster, evaluated_at, cutoff=cutoff, config=config,
                ranking_run_id=ranking_run_id,
            )
        return "expired"

    try:
        if session is None:
            return apply()
        with session.begin_nested():
            return apply()
    except Exception as exc:
        logging.exception("Skipping expiry for cluster %s: %s", cluster.id, exc)
        return "skipped"


def score_run(
    session, run_id: int, evaluated_at: datetime, config: RankingConfig, *,
    ranking_run_id: int | None, dry_run: bool = False, batch_size: int = 100,
) -> tuple[int, int]:
    """Score every cluster in one clustering run. Return scored and skipped counts."""
    repo = ClusterV2Repository(session)
    scored = skipped = 0
    after_id = 0
    while True:
        clusters = repo.get_ranking_batch(run_id=run_id, after_id=after_id, limit=batch_size)
        if not clusters:
            break
        for cluster in clusters:
            if score_cluster(
                cluster, evaluated_at, config, dry_run=dry_run, ranking_run_id=ranking_run_id,
            ) == "scored":
                scored += 1
            else:
                skipped += 1
        after_id = clusters[-1].id
    return scored, skipped

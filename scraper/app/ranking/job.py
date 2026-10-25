"""Score one page of stories, or one legacy cluster, and isolate a bad row.

The scheduled job scores stories. Cluster helpers remain for the older
observation adapter and are not called by that job.
"""

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


def score_story(
    story, evaluated_at: datetime, config: RankingConfig, *,
    dry_run: bool = False, ranking_run_id: int | None = None,
) -> str:
    """Score one story into story_rank. Return ``scored``, ``duplicate``, or ``skipped``.

    Empty and merged stories are skipped. Validation failures are logged and
    skipped. A story already stored for this run is ``duplicate`` and is not
    counted as a skip. A database error rolls back only this story's
    savepoint. The story row itself is not updated.
    """
    session = object_session(story)

    def apply() -> str:
        if story.merged_into_story_id is not None:
            logging.warning("Skipping merged story %s", story.id)
            return "skipped"
        if not story.memberships:
            logging.warning("Skipping empty story %s", story.id)
            return "skipped"
        saved = persistence.rank_and_save_story(
            story, evaluated_at, config, dry_run=dry_run, ranking_run_id=ranking_run_id,
        )
        if saved is None:
            return "duplicate"
        return "scored"

    try:
        if session is None:
            return apply()
        with session.begin_nested():
            return apply()
    except Exception as exc:
        logging.exception("Skipping story %s: %s", story.id, exc)
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

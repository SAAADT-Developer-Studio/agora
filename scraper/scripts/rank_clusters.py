"""Record observation scores for recent streaming stories.

The score is observation-only. It is not an input to feed ordering, and this
command does not update story rows or any cluster table. Each run inserts
``story_rank`` rows and one ``ranking_run`` row with ``source='story'``.

Full component summaries are kept only on the latest row per story. After
scoring, the run deletes ``story_rank`` rows older than the retention window
and finished ``source='story'`` runs that no longer have any. Cluster rows,
story rows, and ``source='cluster'`` ranking runs are left in place.

Settings come from ``scraper/config/ranking.yaml`` unless ``--config`` points
at another YAML or JSON file. A missing or invalid file exits non-zero and
is logged. The job does not fall back to the Python field defaults.
"""

import argparse
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import logging
from pathlib import Path
import signal


# Transaction-scoped, so it also works through transaction-pooling proxies.
# A dedicated connection holds it while batch connections commit their results.
RANKING_LOCK_KEY = 726_264_001

# Same horizon /novo uses: story.last_article_published_at within 14 days.
DEFAULT_STORY_WINDOW_DAYS = 14
# Independent of --days. A one-off shorter window must not delete the history
# the scheduled 14-day run still records.
STORY_RANK_RETENTION_DAYS = DEFAULT_STORY_WINDOW_DAYS
STORY_RANK_RETENTION_BATCH = 1000


def positive_int(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return number


@contextmanager
def ranking_session():
    from database.unit_of_work import database_session
    from sqlalchemy import text

    with database_session() as uow:
        uow.session.execute(text("SET LOCAL statement_timeout = '120s'"))
        yield uow


def finish_run(run_id: int, status: str, *, error: str | None = None,
               failed_story_id: int | None = None, expired_count: int | None = None) -> None:
    from database.schema import RankingRun
    from sqlalchemy import update

    values = dict(
        status=status, finished_at=datetime.now(timezone.utc),
        error=error, failed_story_id=failed_story_id,
    )
    if expired_count is not None:
        values["expired_count"] = expired_count
    with ranking_session() as uow:
        uow.session.execute(update(RankingRun).where(RankingRun.id == run_id).values(**values))


def _deleted_rows(result) -> int:
    count = getattr(result, "rowcount", None)
    if count is None or count < 0:
        return 0
    return count


def _delete_batches(sql: str, params: dict, *, guard) -> int:
    """Run a bounded DELETE until a batch removes fewer rows than the limit.

    Each batch commits on its own. ``guard`` holds the advisory lock; touching
    it keeps that transaction inside its idle timeout.
    """
    from sqlalchemy import text

    removed_total = 0
    while True:
        with ranking_session() as uow:
            removed = _deleted_rows(uow.session.execute(text(sql), params))
        removed_total += removed
        guard.session.execute(text("SELECT 1"))
        if removed < STORY_RANK_RETENTION_BATCH:
            return removed_total


def retain_story_observations(cutoff: datetime, *, guard) -> int:
    """Delete old story observations. Return how many story_rank rows went.

    Only ``story_rank`` and finished ``ranking_run`` rows with ``source='story'``
    are deleted. A ``running`` story run is left for abandoned-run recovery.
    ``source='cluster'`` runs, stories, and cluster rows are not modified.
    """
    expired = _delete_batches(
        """
        DELETE FROM story_rank
        WHERE (ranking_run_id, story_id) IN (
            SELECT ranking_run_id, story_id
            FROM story_rank
            WHERE ranked_at < :cutoff
            ORDER BY ranked_at
            LIMIT :batch
        )
        """,
        {"cutoff": cutoff, "batch": STORY_RANK_RETENTION_BATCH},
        guard=guard,
    )
    _delete_batches(
        """
        DELETE FROM ranking_run
        WHERE id IN (
            SELECT id FROM ranking_run
            WHERE source = 'story'
              AND status <> 'running'
              AND evaluated_at < :cutoff
              AND NOT EXISTS (
                  SELECT 1 FROM story_rank
                  WHERE story_rank.ranking_run_id = ranking_run.id
              )
            ORDER BY id
            LIMIT :batch
        )
        """,
        {"cutoff": cutoff, "batch": STORY_RANK_RETENTION_BATCH},
        guard=guard,
    )
    return expired


def _score_pages(args, config, *, run_id, evaluated_at, since, guard, scored, skipped, failure):
    """Score stories one committed page at a time. There is no cluster expiry pass."""
    from sqlalchemy import text, update
    from database.schema import RankingRun
    from app.ranking.job import score_story
    from app.ranking.stories import load_story_batch

    after_id = 0
    while True:
        batch_scored = batch_skipped = 0
        with ranking_session() as uow:
            stories = load_story_batch(
                uow.session, since=since, after_id=after_id, limit=args.batch_size,
                ranking_run_id=run_id,
            )
            if not stories:
                break
            for story in stories:
                failure["story_id"] = story.id
                outcome = score_story(
                    story, evaluated_at, config,
                    dry_run=args.dry_run, ranking_run_id=run_id,
                )
                if outcome == "scored":
                    batch_scored += 1
                    if batch_scored % 25 == 0:
                        logging.info("Calculated %d scores so far", scored + batch_scored)
                elif outcome == "skipped":
                    batch_skipped += 1
            failure["story_id"] = None
            after_id = stories[-1].id
            if run_id is not None:
                # Counts and their scores commit together. A failed batch
                # cannot inflate the persisted progress counters.
                uow.session.execute(update(RankingRun).where(RankingRun.id == run_id).values(
                    scored_count=scored + batch_scored,
                    skipped_count=skipped + batch_skipped,
                ))
            # Abort this batch if the connection holding the lock died.
            guard.session.execute(text("SELECT 1"))
        scored += batch_scored
        skipped += batch_skipped
        logging.info(
            "Run %s%s: %d scored, %d skipped",
            run_id, " (dry run; no writes)" if args.dry_run else "",
            scored, skipped,
        )
    return scored, skipped


def run_ranking(args, config) -> None:
    from sqlalchemy import text, update
    from database.schema import RankingRun
    from app.ranking.engine import ALGORITHM_VERSION
    from app.ranking.persistence import RANKING_SOURCE_STORY

    with ranking_session() as guard:
        if not guard.session.scalar(text("SELECT pg_try_advisory_xact_lock(:key)"),
                                    {"key": RANKING_LOCK_KEY}):
            logging.info("Another ranking run is active; skipping this invocation")
            return
        # The worker is bounded to 25 minutes by the deployed service. Keep its
        # lock transaction alive between batches, including expensive scoring.
        guard.session.execute(text("SET LOCAL idle_in_transaction_session_timeout = '30min'"))
        # A failed migration leaves the timer enabled. Exit 0 instead of
        # raising every half hour until story_rank exists. Do this before
        # inserting a ranking_run: that insert needs the source column too.
        if guard.session.scalar(text("SELECT to_regclass('story_rank')")) is None:
            logging.error(
                "story_rank is missing; skipping this ranking run until migrations create it"
            )
            return
        evaluated_at = datetime.now(timezone.utc)
        since = evaluated_at - timedelta(days=args.days)
        run_id = None
        if not args.dry_run:
            with ranking_session() as uow:
                # Owning the lock proves a previous running record was abandoned.
                uow.session.execute(update(RankingRun).where(RankingRun.status == "running").values(
                    status="interrupted", finished_at=evaluated_at,
                    error="Worker disappeared; detected by the next ranking run. Actual stop time unknown.",
                ))
                run = RankingRun(
                    evaluated_at=evaluated_at, started_at=evaluated_at, window_days=args.days,
                    algorithm_version=ALGORITHM_VERSION, config=config.model_dump(mode="json"),
                    source=RANKING_SOURCE_STORY,
                )
                uow.session.add(run)
                uow.session.flush()
                run_id = run.id

        logging.info(
            "Ranking run %s scores stories with last_article_published_at >= %s",
            run_id if run_id is not None else "dry-run", since,
        )
        scored = skipped = expired = 0
        failure = {"story_id": None}
        try:
            scored, skipped = _score_pages(
                args, config, run_id=run_id, evaluated_at=evaluated_at, since=since,
                guard=guard, scored=scored, skipped=skipped, failure=failure,
            )
            if run_id is not None:
                guard.session.execute(text("SELECT 1"))
                finish_run(run_id, "succeeded")
        except BaseException as exc:
            if run_id is not None:
                try:
                    finish_run(
                        run_id, "failed" if isinstance(exc, Exception) else "interrupted",
                        error=f"{type(exc).__name__}: {exc}"[:2000],
                        failed_story_id=failure["story_id"],
                    )
                except Exception:
                    logging.exception("Could not finalize ranking run %s; next run will recover it", run_id)
            logging.exception("Ranking run %s stopped; current batch rolled back", run_id)
            raise
        if run_id is not None:
            # Scores are already committed. Retention must not turn that into
            # a failed run, or the timer looks like scoring broke.
            try:
                cutoff = evaluated_at - timedelta(days=STORY_RANK_RETENTION_DAYS)
                expired = retain_story_observations(cutoff, guard=guard)
                with ranking_session() as uow:
                    uow.session.execute(update(RankingRun).where(RankingRun.id == run_id).values(
                        expired_count=expired,
                    ))
            except Exception:
                logging.exception(
                    "Retention for ranking run %s failed; scored rows are already saved",
                    run_id,
                )
                expired = 0
        logging.info(
            "Finished run %s%s: %d scored, %d expired, %d skipped. Evaluation time: %s",
            run_id, " (dry run; no writes)" if args.dry_run else "",
            scored, expired, skipped, evaluated_at,
        )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--days", type=positive_int, default=DEFAULT_STORY_WINDOW_DAYS,
        help="Score stories whose latest article was published within this many days (default: 14)",
    )
    parser.add_argument("--batch-size", type=positive_int, default=100, help="Stories per transaction (default: 100)")
    parser.add_argument(
        "--config", type=Path, default=None,
        help=(
            "YAML or JSON {version, parameters} file "
            "(default: scraper/config/ranking.yaml). "
            "A missing or invalid file fails the run; code defaults are not used."
        ),
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview scores without any database writes")
    args = parser.parse_args(argv)

    # --help requires neither a database URL nor any LLM/API credentials.
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    from app.ranking.config_file import (
        RankingConfigFileError, load_ranking_config_file, packaged_ranking_config_path,
    )

    config_path = args.config if args.config is not None else packaged_ranking_config_path()
    args.config = config_path
    try:
        config = load_ranking_config_file(config_path)
    except RankingConfigFileError as exc:
        logging.error("%s", exc)
        raise SystemExit(1) from exc
    logging.info("Loaded ranking config %s version %s", config_path, config.version)
    run_ranking(args, config)


def handle_termination(signum, frame) -> None:
    # GNU timeout/docker stop send SIGTERM. Unwind the active transaction and
    # persist interruption before exiting; SIGKILL is recovered on the next run.
    raise SystemExit(128 + signum)


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, handle_termination)
    main()

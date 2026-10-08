"""Score the latest production clustering run and expire older ranking data.

The score is observation-only. It is not an input to feed ordering.
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
               failed_cluster_id: int | None = None) -> None:
    from database.schema import RankingRun
    from sqlalchemy import update

    with ranking_session() as uow:
        uow.session.execute(update(RankingRun).where(RankingRun.id == run_id).values(
            status=status, finished_at=datetime.now(timezone.utc),
            error=error, failed_cluster_id=failed_cluster_id,
        ))


def _run_ids(args) -> tuple[int | None, int | None]:
    """Return the run to score and the latest production run to keep.

    Scoring defaults to the latest production run. ``--run-id`` backfills another
    run. Expiry always keeps the latest production run, so a backfill cannot
    clear the clusters the site is showing.
    """
    with ranking_session() as uow:
        production_id = uow.cluster_runs.get_latest_production_id()
    target_id = args.run_id if args.run_id is not None else production_id
    return target_id, production_id


def _run_phase(phase, args, config, *, run_id, evaluated_at, since, target_run_id,
               keep_run_id, guard, scored, expired, skipped, failure):
    """Advance one phase. Expiry does not wait on scoring, and neither shares a cursor."""
    from sqlalchemy import text, update
    from database.schema import RankingRun
    from app.ranking.job import expire_cluster, score_cluster

    after_id = 0
    while True:
        batch_scored = batch_expired = batch_skipped = 0
        with ranking_session() as uow:
            if phase == "score":
                if target_run_id is None:
                    break
                clusters = uow.clusters_v2.get_ranking_batch(
                    run_id=target_run_id, after_id=after_id, limit=args.batch_size,
                )
            else:
                clusters = uow.clusters_v2.get_expired_ranking_batch(
                    before=since, keep_run_id=keep_run_id,
                    after_id=after_id, limit=args.batch_size,
                )
            if not clusters:
                break
            for cluster in clusters:
                failure["cluster_id"] = cluster.id
                if phase == "expire":
                    outcome = expire_cluster(
                        cluster, evaluated_at, cutoff=since, config=config,
                        ranking_run_id=run_id, dry_run=args.dry_run,
                    )
                    if outcome == "expired":
                        batch_expired += 1
                    else:
                        batch_skipped += 1
                else:
                    outcome = score_cluster(
                        cluster, evaluated_at, config,
                        dry_run=args.dry_run, ranking_run_id=run_id,
                    )
                    if outcome == "scored":
                        batch_scored += 1
                        if batch_scored % 25 == 0:
                            logging.info("Calculated %d scores so far", scored + batch_scored)
                    else:
                        batch_skipped += 1
            failure["cluster_id"] = None
            after_id = clusters[-1].id
            if run_id is not None:
                # Counts and their scores commit together. A failed batch
                # cannot inflate the persisted progress counters.
                uow.session.execute(update(RankingRun).where(RankingRun.id == run_id).values(
                    scored_count=scored + batch_scored,
                    expired_count=expired + batch_expired,
                    skipped_count=skipped + batch_skipped,
                ))
            # Abort this batch if the connection holding the lock died.
            guard.session.execute(text("SELECT 1"))
        scored += batch_scored
        expired += batch_expired
        skipped += batch_skipped
        logging.info("Run %s%s: %d scored, %d expired, %d skipped",
                     run_id, " (dry run; no writes)" if args.dry_run else "",
                     scored, expired, skipped)
    return scored, expired, skipped


def run_ranking(args, config) -> None:
    from sqlalchemy import text, update
    from database.schema import RankingRun
    from app.ranking.engine import ALGORITHM_VERSION

    with ranking_session() as guard:
        if not guard.session.scalar(text("SELECT pg_try_advisory_xact_lock(:key)"),
                                    {"key": RANKING_LOCK_KEY}):
            logging.info("Another ranking run is active; skipping this invocation")
            return
        # The worker is bounded to 25 minutes by the deployed service. Keep its
        # lock transaction alive between batches, including expensive scoring.
        guard.session.execute(text("SET LOCAL idle_in_transaction_session_timeout = '30min'"))
        evaluated_at = datetime.now(timezone.utc)
        since = evaluated_at - timedelta(days=args.days)
        target_run_id, production_run_id = _run_ids(args)
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
                )
                uow.session.add(run)
                uow.session.flush()
                run_id = run.id

        if target_run_id is None:
            logging.warning("No production clustering run to score; expiry still runs")
        logging.info(
            "Ranking run %s scores cluster run %s; ranking data outside that run expires before %s",
            run_id if run_id is not None else "dry-run", target_run_id, since,
        )
        scored = expired = skipped = 0
        failure = {"cluster_id": None}
        try:
            # Expiry is its own pass. It does not wait for scoring to finish,
            # and it does not use the scoring cursor.
            for phase in ("expire", "score"):
                scored, expired, skipped = _run_phase(
                    phase, args, config, run_id=run_id, evaluated_at=evaluated_at,
                    since=since, target_run_id=target_run_id, keep_run_id=production_run_id,
                    guard=guard,
                    scored=scored, expired=expired, skipped=skipped, failure=failure,
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
                        failed_cluster_id=failure["cluster_id"],
                    )
                except Exception:
                    logging.exception("Could not finalize ranking run %s; next run will recover it", run_id)
            logging.exception("Ranking run %s stopped; current batch rolled back", run_id)
            raise
        logging.info("Finished run %s%s: %d scored, %d expired, %d skipped. Evaluation time: %s",
                     run_id, " (dry run; no writes)" if args.dry_run else "",
                     scored, expired, skipped, evaluated_at)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=positive_int, default=30,
                        help="Expire ranking data on other runs older than this many days (default: 30)")
    parser.add_argument("--run-id", type=positive_int,
                        help="Cluster run to score (default: latest is_production run)")
    parser.add_argument("--batch-size", type=positive_int, default=100, help="Clusters per transaction (default: 100)")
    parser.add_argument("--config", type=Path, help="JSON RankingConfig with version and parameters")
    parser.add_argument("--dry-run", action="store_true", help="Preview scores and expiry without any database writes")
    args = parser.parse_args(argv)

    # --help requires neither a database URL nor any LLM/API credentials.
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
    from app.ranking.contracts import RankingConfig
    from app.ranking.persistence import (
        DEFAULT_CONFIG_VERSION, resolve_ranking_config,
    )

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    config = resolve_ranking_config(
        RankingConfig.model_validate_json(args.config.read_text()) if args.config
        else RankingConfig(version=DEFAULT_CONFIG_VERSION)
    )
    run_ranking(args, config)


def handle_termination(signum, frame) -> None:
    # GNU timeout/docker stop send SIGTERM. Unwind the active transaction and
    # persist interruption before exiting; SIGKILL is recovered on the next run.
    raise SystemExit(128 + signum)


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, handle_termination)
    main()

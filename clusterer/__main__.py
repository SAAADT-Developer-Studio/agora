import logging
from pathlib import Path

from apscheduler.schedulers.blocking import BlockingScheduler
from dotenv import load_dotenv


def main() -> None:
    load_dotenv()
    load_dotenv(Path(__file__).resolve().parent.parent / "scraper" / ".env")
    logging.basicConfig(level=logging.INFO)
    from .run import run

    scheduler = BlockingScheduler()
    scheduler.add_job(run, "cron", minute="*/15")
    run()
    scheduler.start()


if __name__ == "__main__":
    main()

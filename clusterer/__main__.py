import logging

from apscheduler.schedulers.blocking import BlockingScheduler
from dotenv import find_dotenv, load_dotenv


def main() -> None:
    load_dotenv(find_dotenv())
    logging.basicConfig(level=logging.INFO)
    from .run import run

    scheduler = BlockingScheduler()
    scheduler.add_job(run, "cron", minute="*/15")
    run()
    scheduler.start()


if __name__ == "__main__":
    main()

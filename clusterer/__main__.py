import logging

from apscheduler.schedulers.blocking import BlockingScheduler


def run() -> None:
    logging.info("clusterer running")


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    scheduler = BlockingScheduler()
    scheduler.add_job(run, "cron", minute="*/15")
    run()
    scheduler.start()


if __name__ == "__main__":
    main()

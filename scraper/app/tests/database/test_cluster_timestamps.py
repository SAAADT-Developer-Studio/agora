from datetime import datetime, timedelta, timezone
import os
import time

from database.schema import ClusterRun, ClusterV2


def test_new_clusters_use_current_utc_even_when_machine_uses_local_summer_time():
    previous = os.environ.get("TZ")
    os.environ["TZ"] = "Europe/Ljubljana"
    time.tzset()
    try:
        before = datetime.now(timezone.utc)
        run = ClusterRun(algo_version="test", params={})
        cluster = ClusterV2(title="Test", slug="test", run_id=1)
        after = datetime.now(timezone.utc)

        for timestamp in (run.created_at, cluster.created_at):
            assert timestamp.utcoffset() == timedelta(0)
            assert before <= timestamp <= after
    finally:
        if previous is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = previous
        time.tzset()

"""A reminted cluster stays hidden when it still contains a hidden cluster's articles."""

from database.schema import ArticleCluster, ClusterV2
from app.clusterer.run_clustering import hidden_member_ids, inherits_hidden


def _cluster(*article_ids: int, hidden: bool = False) -> ClusterV2:
    cluster = ClusterV2(title="Story", slug=f"story-{article_ids}", run_id=1, hidden=hidden)
    for article_id in article_ids:
        cluster.memberships.append(
            ArticleCluster(article_id=article_id, cluster_id=1, run_id=1)
        )
    return cluster


def test_nothing_hidden_is_a_no_op():
    previous = [_cluster(1, 2), _cluster(3)]
    assert hidden_member_ids(previous) == set()
    assert inherits_hidden([1, 2], hidden_member_ids(previous)) is False


def test_identical_membership_stays_hidden():
    previous = [_cluster(1, 2, 3, hidden=True)]
    hidden_ids = hidden_member_ids(previous)
    assert inherits_hidden([1, 2, 3], hidden_ids) is True


def test_one_shared_article_stays_hidden_when_membership_drifts():
    # Hash match only covers an identical set. HDBSCAN adds or drops a member
    # on most runs, which would publish a new visible row.
    previous = [_cluster(1, 2, 3, hidden=True), _cluster(4, 5)]
    hidden_ids = hidden_member_ids(previous)
    assert inherits_hidden([2, 3, 9], hidden_ids) is True
    assert inherits_hidden([4, 5, 6], hidden_ids) is False


def test_split_and_merge_both_stay_hidden():
    previous = [_cluster(1, 2, 3, 4, hidden=True)]
    hidden_ids = hidden_member_ids(previous)
    assert inherits_hidden([1, 2], hidden_ids) is True
    assert inherits_hidden([3, 4], hidden_ids) is True
    assert inherits_hidden([1, 2, 3, 4, 5], hidden_ids) is True


def test_visible_overlap_does_not_hide_a_new_cluster():
    previous = [_cluster(1, 2, hidden=True), _cluster(3, 4)]
    hidden_ids = hidden_member_ids(previous)
    assert inherits_hidden([3, 4], hidden_ids) is False
    assert inherits_hidden([8, 9], hidden_ids) is False
    assert inherits_hidden([], hidden_ids) is False

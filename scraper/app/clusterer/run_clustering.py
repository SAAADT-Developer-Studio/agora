from collections.abc import Sequence
from app.database.schema import Article, ClusterRun, ClusterV2, ArticleCluster
from app.database.unit_of_work import UnitOfWork
from datetime import datetime, timedelta, timezone
from app.clusterer.cluster import cluster
from app.clusterer.hash_cluster import hash_cluster
from app.clusterer.generate_cluster_titles import generate_cluster_titles
import heapq
import itertools
import logging

from app.utils.slugify import slugify


def get_hash_to_cluster_mapping(clusters: Sequence[ClusterV2]) -> dict[int, ClusterV2]:
    hash_to_cluster_mapping = dict()
    for cluster in clusters:
        cluster_articles = [membership.article for membership in cluster.memberships]
        cluster_hash = hash_cluster(cluster_articles)
        hash_to_cluster_mapping[cluster_hash] = cluster
    return hash_to_cluster_mapping


def filter_old_clusters(clusters: Sequence[ClusterV2], days: int = 3) -> Sequence[ClusterV2]:
    cutoff_date = datetime.now(timezone.utc) - timedelta(days=days)
    filtered_clusters: list[ClusterV2] = []
    for cluster in clusters:
        if (
            len(cluster.memberships) > 0
            and max(m.article.published_at for m in cluster.memberships) > cutoff_date
        ):
            filtered_clusters.append(cluster)
    return filtered_clusters


async def run_clustering(uow: UnitOfWork):
    prev_run = uow.cluster_runs.get_latest()
    if prev_run is None:
        raise Exception("No previous cluster run found. Something is very wrong.")

    current_run = ClusterRun(
        algo_version="hdbscan-1.0.0",
        is_production=True,
        params=None,
    )
    uow.cluster_runs.create(current_run)
    uow.session.flush()

    prev_clusters = filter_old_clusters(
        clusters=prev_run.clusters,
        days=3,
    )

    prev_articles = list(
        itertools.chain.from_iterable(
            [m.article for m in cluster.memberships] for cluster in prev_clusters
        )
    )

    latest_article_date = (
        max(article.published_at for article in prev_articles)
        if len(prev_articles) > 0
        else datetime.now(timezone.utc) - timedelta(days=3)
    )

    new_articles = uow.articles.get_all_since(latest_article_date)

    # limit to 6000 just in case
    articles = heapq.nlargest(
        6000, itertools.chain(prev_articles, new_articles), key=lambda a: a.published_at
    )

    if len(articles) == 0:  # remove this
        logging.warning("No articles to cluster. Exiting.")
        return

    cluster_articles_map = cluster(articles)

    clusters_pending_title_generation: list[list[Article]] = []
    hash_to_cluster_mapping = get_hash_to_cluster_mapping(prev_clusters)

    final: list[tuple[str, list[Article]]] = []

    for label, cluster_articles in cluster_articles_map.items():
        cluster_hash = hash_cluster(cluster_articles)
        if cluster_hash in hash_to_cluster_mapping:
            final.append((hash_to_cluster_mapping[cluster_hash].title, cluster_articles))
        else:
            clusters_pending_title_generation.append(cluster_articles)

    generated_titles = await generate_cluster_titles(clusters_pending_title_generation)

    final.extend(zip(generated_titles, clusters_pending_title_generation))
    new_clusters: list[ClusterV2] = []

    for i, (title, cluster_articles) in enumerate(final):
        date_str = datetime.now().strftime("%Y-%m-%d-%H-%M")
        cluster_v2 = ClusterV2(
            title=title,
            slug=f"{slugify(title)}-{date_str}-{i}",
            run_id=current_run.id,
        )
        for article in cluster_articles:
            cluster_v2.memberships.append(
                ArticleCluster(
                    article_id=article.id,
                    cluster_id=cluster_v2.id,
                    run_id=current_run.id,
                )
            )
        new_clusters.append(cluster_v2)
    uow.clusters_v2.bulk_create(new_clusters)

    logging.info(f"Created {len(generated_titles)} new clusters.")
    logging.info(f"Kept {len(final) - len(generated_titles)} clusters.")


# this is a function to bootstrap the clustering run for existing articles
# in case something goes terribly wrong
async def bootstrap_cluster_run(uow: UnitOfWork) -> None:
    print("Bootstrapping clustering run...")
    cluster_run = ClusterRun(
        algo_version="hdbscan-1.0.0",
        is_production=True,
        params=None,
    )
    uow.cluster_runs.create(cluster_run)
    # Flush to get the cluster_run.id assigned by the database
    uow.session.flush()

    articles = uow.articles.get_latest(3000)

    cluster_articles_map = cluster(articles)
    clusters: list[ClusterV2] = []

    for label, cluster_articles in cluster_articles_map.items():
        title = cluster_articles[0].title
        cluster_v2 = ClusterV2(
            title=title,
            slug=slugify(title),
            run_id=cluster_run.id,
        )
        clusters.append(cluster_v2)
        for article in cluster_articles:
            cluster_v2.memberships.append(
                ArticleCluster(
                    article_id=article.id,
                    cluster_id=cluster_v2.id,
                    run_id=cluster_run.id,
                )
            )
    uow.clusters_v2.bulk_create(clusters)


async def migrate_clusters(uow: UnitOfWork) -> None:
    print("Migrating clusters to ClusterV2...")
    cluster_run = ClusterRun(
        algo_version="hdbscan-1.0.0",
        is_production=True,
        params=None,
    )
    uow.cluster_runs.create(cluster_run)
    # Flush to get the cluster_run.id assigned by the database
    uow.session.flush()

    old_clusters = uow.clusters.get_all_nonempty()
    clusters_v2: list[ClusterV2] = []

    for old_cluster in old_clusters:
        cluster_v2 = ClusterV2(
            title=old_cluster.title,
            slug=old_cluster.slug,
            run_id=cluster_run.id,
        )
        clusters_v2.append(cluster_v2)
        for article in old_cluster.articles:
            cluster_v2.memberships.append(
                ArticleCluster(
                    article_id=article.id,
                    cluster_id=cluster_v2.id,
                    run_id=cluster_run.id,
                )
            )
    uow.clusters_v2.bulk_create(clusters_v2)

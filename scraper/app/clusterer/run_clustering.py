import heapq
import itertools
import logging
from collections.abc import Sequence
from datetime import datetime, timedelta, timezone

from langchain.chat_models import BaseChatModel

from app.clusterer.cluster import cluster
from app.clusterer.generate_cluster_titles import generate_cluster_titles
from app.clusterer.hash_cluster import hash_cluster
from app.database.schema import Article, ArticleCluster, ClusterRun, ClusterV2
from app.database.unit_of_work import UnitOfWork
from app.integrations.wikimedia import lookup_wikimedia_images_for_clusters
from app.utils.slugify import slugify


type ClusterPayload = tuple[
    str,
    list[Article],
    list[str],
    list[dict[str, object]],
    datetime | None,
    datetime | None,
]

MAX_WIKIMEDIA_LOOKUPS_PER_RUN = 10
WIKIMEDIA_LOOKUP_TTL = timedelta(hours=24)
WIKIMEDIA_FAILURE_RETRY_DELAY = timedelta(hours=1)


def _has_complete_wikimedia_data(
    image_urls: list[str], image_metadata: list[dict[str, object]]
) -> bool:
    if not image_urls and not image_metadata:
        return True
    if len(image_urls) != len(image_metadata):
        return False
    for image_url, metadata in zip(image_urls, image_metadata):
        if not isinstance(metadata, dict):
            return False
        source_url = metadata.get("source_url")
        license_name = metadata.get("license")
        if (
            metadata.get("url") != image_url
            or not isinstance(source_url, str)
            or not source_url.startswith("https://commons.wikimedia.org/")
            or not isinstance(license_name, str)
            or not license_name
        ):
            return False
        if license_name.casefold() not in {"cc0", "cc0 1.0", "public domain"} and (
            not isinstance(metadata.get("attribution"), str)
            or not isinstance(metadata.get("license_url"), str)
        ):
            return False
    return True


def _select_wikimedia_lookup_indexes(
    unresolved_indexes: list[int],
) -> list[int]:
    if len(unresolved_indexes) <= MAX_WIKIMEDIA_LOOKUPS_PER_RUN:
        return unresolved_indexes

    selected = unresolved_indexes[:MAX_WIKIMEDIA_LOOKUPS_PER_RUN]
    logging.info(
        "Deferring %d Wikimedia lookups to later clustering runs",
        len(unresolved_indexes) - len(selected),
    )
    return selected


async def enrich_cluster_payloads_with_wikimedia(
    cluster_payloads: list[ClusterPayload],
) -> list[ClusterPayload]:
    """Populate unresolved clusters without letting Wikimedia failures abort clustering."""

    enriched = [
        payload
        if _has_complete_wikimedia_data(payload[2], payload[3])
        else (payload[0], payload[1], [], [], None, None)
        for payload in cluster_payloads
    ]
    now = datetime.now(timezone.utc)
    lookup_cutoff = now - WIKIMEDIA_LOOKUP_TTL
    retry_cutoff = now - WIKIMEDIA_FAILURE_RETRY_DELAY
    never_attempted_indexes = [
        index
        for index, (_, _, _, _, lookup_at, last_attempt_at) in enumerate(enriched)
        if (lookup_at is None or lookup_at < lookup_cutoff) and last_attempt_at is None
    ]
    retryable_indexes = [
        index
        for index, (_, _, _, _, lookup_at, last_attempt_at) in enumerate(enriched)
        if (lookup_at is None or lookup_at < lookup_cutoff)
        and last_attempt_at is not None
        and last_attempt_at < retry_cutoff
    ]
    unresolved_indexes = never_attempted_indexes + retryable_indexes
    if not unresolved_indexes:
        return enriched
    unresolved_indexes = _select_wikimedia_lookup_indexes(unresolved_indexes)

    titles = [enriched[index][0] for index in unresolved_indexes]
    try:
        lookup_results = await lookup_wikimedia_images_for_clusters(titles)
    except Exception:
        logging.exception("Unexpected failure while enriching clusters with Wikimedia images")
        return enriched

    if len(lookup_results) != len(unresolved_indexes):
        logging.error(
            "Wikimedia returned %d lookup results for %d clusters",
            len(lookup_results),
            len(unresolved_indexes),
        )
        return enriched

    attempted_at = datetime.now(timezone.utc)
    for cluster_index, lookup_result in zip(unresolved_indexes, lookup_results):
        title, articles, image_urls, image_metadata, lookup_at, _ = enriched[cluster_index]
        if not lookup_result.completed:
            enriched[cluster_index] = (
                title,
                articles,
                image_urls,
                image_metadata,
                lookup_at,
                attempted_at,
            )
            continue
        images = lookup_result.images
        enriched[cluster_index] = (
            title,
            articles,
            [image.url for image in images],
            [image.to_metadata() for image in images],
            attempted_at,
            attempted_at,
        )

    image_count = sum(len(payload[2]) for payload in enriched)
    logging.info(
        "Connected %d Wikimedia images to %d clusters",
        image_count,
        len(enriched),
    )
    return enriched


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


async def run_clustering(uow: UnitOfWork, model: BaseChatModel):
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

    if len(articles) == 0:
        logging.warning("No articles to cluster. Exiting.")
        return

    cluster_articles_map = cluster(articles)

    clusters_pending_title_generation: list[list[Article]] = []
    hash_to_cluster_mapping = get_hash_to_cluster_mapping(prev_clusters)

    final: list[ClusterPayload] = []

    for label, cluster_articles in cluster_articles_map.items():
        cluster_hash = hash_cluster(cluster_articles)
        if cluster_hash in hash_to_cluster_mapping:
            existing_cluster = hash_to_cluster_mapping[cluster_hash]
            final.append(
                (
                    existing_cluster.title,
                    cluster_articles,
                    list(existing_cluster.wiki_image_urls or []),
                    list(existing_cluster.wiki_image_metadata or []),
                    existing_cluster.wiki_image_lookup_at,
                    existing_cluster.wiki_image_last_attempt_at,
                )
            )
        else:
            clusters_pending_title_generation.append(cluster_articles)

    generated_titles = await generate_cluster_titles(clusters_pending_title_generation, model)

    final.extend(
        (title, cluster_articles, [], [], None, None)
        for title, cluster_articles in zip(generated_titles, clusters_pending_title_generation)
    )
    final = await enrich_cluster_payloads_with_wikimedia(final)
    new_clusters: list[ClusterV2] = []

    for i, (
        title,
        cluster_articles,
        wiki_image_urls,
        wiki_image_metadata,
        wiki_image_lookup_at,
        wiki_image_last_attempt_at,
    ) in enumerate(final):
        date_str = datetime.now().strftime("%Y-%m-%d-%H-%M")
        cluster_v2 = ClusterV2(
            title=title,
            slug=f"{slugify(title)}-{date_str}-{i}",
            run_id=current_run.id,
            wiki_image_urls=wiki_image_urls,
            wiki_image_metadata=wiki_image_metadata,
            wiki_image_lookup_at=wiki_image_lookup_at,
            wiki_image_last_attempt_at=wiki_image_last_attempt_at,
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
    cluster_payloads: list[ClusterPayload] = [
        (cluster_articles[0].title, cluster_articles, [], [], None, None)
        for cluster_articles in cluster_articles_map.values()
    ]
    cluster_payloads = await enrich_cluster_payloads_with_wikimedia(cluster_payloads)
    clusters: list[ClusterV2] = []

    for (
        title,
        cluster_articles,
        wiki_image_urls,
        wiki_image_metadata,
        wiki_image_lookup_at,
        wiki_image_last_attempt_at,
    ) in cluster_payloads:
        cluster_v2 = ClusterV2(
            title=title,
            slug=slugify(title),
            run_id=cluster_run.id,
            wiki_image_urls=wiki_image_urls,
            wiki_image_metadata=wiki_image_metadata,
            wiki_image_lookup_at=wiki_image_lookup_at,
            wiki_image_last_attempt_at=wiki_image_last_attempt_at,
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
    cluster_payloads: list[ClusterPayload] = [
        (old_cluster.title, list(old_cluster.articles), [], [], None, None)
        for old_cluster in old_clusters
    ]
    cluster_payloads = await enrich_cluster_payloads_with_wikimedia(cluster_payloads)
    clusters_v2: list[ClusterV2] = []

    for old_cluster, payload in zip(old_clusters, cluster_payloads):
        (
            title,
            cluster_articles,
            wiki_image_urls,
            wiki_image_metadata,
            wiki_image_lookup_at,
            wiki_image_last_attempt_at,
        ) = payload
        cluster_v2 = ClusterV2(
            title=title,
            slug=old_cluster.slug,
            run_id=cluster_run.id,
            wiki_image_urls=wiki_image_urls,
            wiki_image_metadata=wiki_image_metadata,
            wiki_image_lookup_at=wiki_image_lookup_at,
            wiki_image_last_attempt_at=wiki_image_last_attempt_at,
        )
        clusters_v2.append(cluster_v2)
        for article in cluster_articles:
            cluster_v2.memberships.append(
                ArticleCluster(
                    article_id=article.id,
                    cluster_id=cluster_v2.id,
                    run_id=cluster_run.id,
                )
            )
    uow.clusters_v2.bulk_create(clusters_v2)

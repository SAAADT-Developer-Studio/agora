import asyncio
import hdbscan
import numpy as np
import pandas as pd
from umap import UMAP
from pprint import pprint
from sklearn.preprocessing import Normalizer
from langchain.chat_models import init_chat_model
from typing import Iterable
import logging
import json

from app.database.unit_of_work import database_session, UnitOfWork
from app.database.schema import Article, Cluster
from app.utils.slugify import slugify
from datetime import datetime


def cluster(embeddings: list[np.ndarray]) -> list[int]:
    hdb = hdbscan.HDBSCAN(
        min_samples=2,
        min_cluster_size=2,
        cluster_selection_method="leaf",
        cluster_selection_epsilon=0.15,
    ).fit(embeddings)

    labels: list[int] = hdb.labels_.astype(int)
    return labels


def assign_singletons(labels: list[int]) -> list[int]:
    new_labels = labels.copy()
    cluster_id = max(labels) + 1
    for i, label in enumerate(labels):
        if label == -1:
            new_labels[i] = cluster_id
            cluster_id += 1
    return new_labels


def hash_cluster(articles: list[Article]) -> int:
    return hash(tuple(sorted(article.id for article in articles)))


async def generate_titles_for_clusters(article_lists: Iterable[list[Article]]) -> list[str]:
    # TODO: dont generate titles for clusters with only 1 article
    model = init_chat_model("gemini-2.0-flash", model_provider="google_genai")
    inputs = [
        "You are a professional Slovenian news editor. "
        + "Generate a descriptive and engaging collective title for the following news article titles. "
        + "Write it in slovenian, output only a single title, don't include any other text or try to output markdown.\n\n"
        + "\n".join(
            article.title
            for article in sorted(articles[:5], key=lambda a: a.published_at, reverse=True)
        )
        for articles in article_lists
    ]
    results = await model.abatch(inputs=inputs)
    # langchain returns some weird ass structure
    titles = [result.content for result in results]
    return titles
    # return [articles[0].title for articles in article_lists]


async def run_clustering(uow: UnitOfWork, new_articles: list[Article]):
    prev_articles = uow.articles.get_clustered_and_pad_articles()

    prev_clusters: dict[int, list[Article]] = {}

    for article in prev_articles:
        if article.cluster_id is not None:
            prev_clusters.setdefault(article.cluster_id, []).append(article)

    existing_cluster_hashes = set()
    existing_cluster_hash_to_id: dict[int, int] = {}

    for cluster_id, cluster_articles in prev_clusters.items():
        cluster_hash = hash_cluster(cluster_articles)
        existing_cluster_hash_to_id[cluster_hash] = cluster_id
        existing_cluster_hashes.add(cluster_hash)

    articles = prev_articles + new_articles
    embeddings: list[np.ndarray] = [
        np.array(article.embedding) for article in prev_articles + new_articles
    ]
    labels = assign_singletons(cluster(embeddings))

    clusters: dict[int, list[Article]] = {}
    for label, article in zip(labels, articles):
        assert label != -1, "Label -1 should not be present after assign_singletons"
        clusters.setdefault(label, []).append(article)

    unchanged_prev_cluster_ids = set()
    unchanged_cluster_labels = set()

    for label, cluster_articles in clusters.items():
        cluster_hash = hash_cluster(cluster_articles)
        if cluster_hash in existing_cluster_hashes:
            unchanged_prev_cluster_ids.add(existing_cluster_hash_to_id[cluster_hash])
            unchanged_cluster_labels.add(label)

    clusters_to_delete = set(prev_clusters.keys()) - unchanged_prev_cluster_ids

    uow.clusters.delete_by_ids(list(clusters_to_delete))

    clusters_to_add = list(set(clusters.keys()) - unchanged_cluster_labels)

    titles: list[str] = await generate_titles_for_clusters(
        clusters[label] for label in clusters_to_add
    )

    date_str = datetime.now().strftime("%Y-%m-%d")
    clusters_to_create: list[Cluster] = [
        Cluster(title=title, slug=f"{slugify(title)}-{date_str}") for title in titles
    ]

    cluster_articles_count = sum(len(clusters[label]) for label in clusters_to_add)
    unchanged_cluster_articles_count = sum(
        len(prev_clusters[cluster_id]) for cluster_id in unchanged_prev_cluster_ids
    )
    logging.info(
        f"Creating {len(clusters_to_create)} new clusters containing {cluster_articles_count} articles."
    )
    logging.info(
        f"Keeping {len(unchanged_cluster_labels)} clusters containing {unchanged_cluster_articles_count} articles."
    )

    uow.clusters.bulk_create(clusters_to_create)
    uow.session.flush()  # Ensure IDs are assigned to clusters

    # assign articles their cluster IDs
    for label, created_cluster in zip(clusters_to_add, clusters_to_create):
        for article in clusters[label]:
            article.cluster_id = created_cluster.id

    uow.clusters.delete_old_clusters()


if __name__ == "__main__":
    # with database_session() as uow:
    #     articles = uow.articles.get_articles_with_summaries()
    #     print(f"Found {len(articles)} articles with summaries.")
    #     parsed_articles = [
    #         {"summary": article.summary, "url": article.url, "embedding": article.embedding}
    #         for article in articles
    #         if article
    #     ]

    #     json.dump(parsed_articles, open("./articles.json", "w"), indent=2, ensure_ascii=False)
    #     return

    with database_session() as uow:
        asyncio.run(run_clustering(uow, []))

    exit()
    articles = json.load(open("./articles.json", "r"))

    embeddings = [np.array(article["embedding"]) for article in articles]

    # reducer_clust = UMAP(
    #     n_components=50, random_state=42, n_neighbors=30, min_dist=0.0, metric="cosine"
    # )
    # emb_50 = reducer_clust.fit_transform(embeddings)
    labels = cluster(embeddings)

    label_map: dict[str, list[str]] = {}
    for article, label in zip(articles, labels):
        label_map.setdefault(str(label), []).append(article["summary"])

    json.dump(label_map, open("./clusters.json", "w"), indent=2, ensure_ascii=False)

    umap = UMAP(n_components=2, random_state=42, n_neighbors=80, min_dist=0.1)

    df_umap = (
        pd.DataFrame(umap.fit_transform(np.array(embeddings)), columns=["x", "y"])
        .assign(cluster=lambda df: labels)
        .query('cluster != "-1"')
        .sort_values(by="cluster")
    )

    import plotly.express as px

    fig = px.scatter(df_umap, x="x", y="y", color="cluster")
    fig.show()

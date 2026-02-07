import asyncio
import hdbscan
import numpy as np
import pandas as pd
from umap import UMAP
from sklearn.preprocessing import Normalizer
from typing import Sequence
import logging
import json

from app.database.unit_of_work import database_session, UnitOfWork
from app.database.schema import Article


def cluster_impl(embeddings: list[np.ndarray]) -> list[int]:
    hdb = hdbscan.HDBSCAN(
        min_samples=2,
        min_cluster_size=2,
        cluster_selection_method="leaf",
        cluster_selection_epsilon=0.2,
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


def cluster(articles: Sequence[Article]) -> dict[int, list[Article]]:
    embeddings = [np.array(article.embedding, dtype=np.float64) for article in articles]
    labels = assign_singletons(cluster_impl(embeddings))
    clusters: dict[int, list[Article]] = {}
    for label, article in zip(labels, articles):
        assert label != -1, "Label -1 should not be present after assign_singletons"
        clusters.setdefault(label, []).append(article)
    return clusters


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

    # with database_session() as uow:
    #     asyncio.run(run_clustering(uow))

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

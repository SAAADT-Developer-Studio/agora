import numpy as np
from sklearn.metrics.pairwise import cosine_distances
import umap
import hdbscan
import json

# Assume 'embeddings' is a numpy array of shape (n_articles, embedding_dim)
# Example: embeddings = np.load('your_embeddings.npy')


def cluster_embeddings(embeddings, min_cluster_size=2, umap_dim=50):
    # Reduce dimensionality with UMAP (preserves structure for clustering)
    reducer = umap.UMAP(n_components=umap_dim, metric="cosine", random_state=42)
    reduced_embeddings = reducer.fit_transform(embeddings)
    reduced_embeddings = reduced_embeddings.astype(np.float64)  # Ensure float64 for HDBSCAN

    # Cluster with HDBSCAN using precomputed cosine distance
    dist_matrix = cosine_distances(reduced_embeddings)
    dist_matrix = dist_matrix.astype(np.float64)  # Ensure float64 for HDBSCAN
    clusterer = hdbscan.HDBSCAN(
        min_cluster_size=min_cluster_size,
        metric="precomputed",
    )
    labels = clusterer.fit_predict(dist_matrix)

    # labels: array of cluster IDs (-1 for noise)
    return labels.astype(str)


# Usage
# labels = cluster_embeddings(embeddings)
# Print cluster assignments or analyze


articles = json.load(open("./articles.json", "r"))

embeddings = [np.array(article["embedding"]) for article in articles]

labels = cluster_embeddings(embeddings)

label_map = {}
for article, label in zip(articles, labels):
    label_map.setdefault(str(label), []).append(article["summary"])

json.dump(label_map, open("./clusters.json", "w"), indent=2, ensure_ascii=False)

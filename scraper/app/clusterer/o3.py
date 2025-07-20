import numpy as np
from sklearn.decomposition import PCA
from sklearn.preprocessing import normalize
import hdbscan
from sklearn.metrics.pairwise import cosine_distances

# X: (n_articles, dim) float32 Gemini embeddings -------------
X = np.load("news_embeddings.npy")  # shape (n, d)

# 1. ℓ2 normalisation
X = normalize(X, norm="l2")

# 2. Dimensionality reduction
pca = PCA(n_components=100, random_state=42)
X_red = pca.fit_transform(X).astype("float32")

# 3. Density-based clustering
clusterer = hdbscan.HDBSCAN(
    min_cluster_size=12,  # lower → more granular events
    min_samples=4,  # higher → stricter core definition
    metric="euclidean",  # fine after PCA
    cluster_selection_method="eom",  # Excess of Mass
    prediction_data=True,
)
labels = clusterer.fit_predict(X_red)  # −1 = noise

# 4. Optional centroid-based merging -------------------------
unique = np.unique(labels[labels >= 0])
centroids = np.stack([X[labels == c].mean(0) for c in unique])

dmat = cosine_distances(centroids)
np.fill_diagonal(dmat, 1.0)
merge_pairs = np.transpose(np.nonzero(dmat < 0.05))

# Union–find to merge close clusters
parent = {c: c for c in unique}


def find(c):
    while parent[c] != c:
        c = parent[c]
    return c


for i, j in merge_pairs:
    a, b = find(unique[i]), find(unique[j])
    if a != b:
        parent[b] = a

# Map old labels → merged labels
merge_map = {c: find(c) for c in unique}
final_labels = np.array([-1 if l == -1 else merge_map[l] for l in labels], dtype=int)

# ------------------------------------------------------------
np.save("event_labels.npy", final_labels)
print("clusters:", len(set(final_labels)) - (-1 in final_labels))

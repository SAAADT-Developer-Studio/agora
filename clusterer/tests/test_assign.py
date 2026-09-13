from clusterer.assign import COSINE, JOIN_THRESHOLD, SEED, NeighborIndex, decide


def test_empty_index_seeds() -> None:
    assignment = decide([1.0, 0.0], NeighborIndex())
    assert assignment.story_id is None
    assert assignment.method == SEED
    assert assignment.similarity is None
    assert assignment.nearest_article_id is None


def test_identical_embedding_joins() -> None:
    index = NeighborIndex()
    index.add(article_id=1, story_id=10, embedding=[1.0, 0.0])

    assignment = decide([1.0, 0.0], index)

    assert assignment.story_id == 10
    assert assignment.method == COSINE
    assert assignment.nearest_article_id == 1
    assert assignment.similarity == 1.0


def test_below_threshold_seeds() -> None:
    index = NeighborIndex()
    index.add(article_id=1, story_id=10, embedding=[1.0, 0.0])

    assignment = decide([0.0, 1.0], index)

    assert assignment.story_id is None
    assert assignment.method == SEED
    assert assignment.similarity is None
    assert assignment.nearest_article_id is None


def test_just_above_threshold_joins() -> None:
    index = NeighborIndex()
    index.add(article_id=1, story_id=10, embedding=[1.0, 0.0])
    above = JOIN_THRESHOLD + 0.01
    embedding = [above, (1.0 - above**2) ** 0.5]

    assignment = decide(embedding, index)

    assert assignment.story_id == 10
    assert assignment.method == COSINE
    assert assignment.similarity is not None
    assert assignment.similarity > JOIN_THRESHOLD


def test_just_below_threshold_seeds() -> None:
    index = NeighborIndex()
    index.add(article_id=1, story_id=10, embedding=[1.0, 0.0])
    below = JOIN_THRESHOLD - 0.01
    embedding = [below, (1.0 - below**2) ** 0.5]

    assignment = decide(embedding, index)

    assert assignment.story_id is None
    assert assignment.method == SEED


def test_later_article_in_batch_can_join_earlier_seed() -> None:
    index = NeighborIndex()
    first = decide([1.0, 0.0], index)
    assert first.method == SEED

    index.add(article_id=1, story_id=42, embedding=[1.0, 0.0])
    second = decide([1.0, 0.0], index)

    assert second.story_id == 42
    assert second.method == COSINE
    assert second.nearest_article_id == 1

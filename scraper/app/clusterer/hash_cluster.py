from app.database.schema import Article


def hash_cluster(articles: list[Article]) -> int:
    return hash(tuple(sorted(article.id for article in articles)))

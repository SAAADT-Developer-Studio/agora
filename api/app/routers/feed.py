"""Feed-related API endpoints."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
import sqlalchemy

from ..database import get_db
from ..models import Article, Cluster, NewsProvider
import math
from datetime import datetime, timedelta, date


def average_date(dates: list[datetime]) -> float:

    # Calculate the total seconds from epoch
    total_seconds = sum(dt.timestamp() for dt in dates)
    avg_timestamp = total_seconds / len(dates)
    return avg_timestamp


router = APIRouter(prefix="/feed", tags=["feed"])

# time
# number of articles
# ranks of the news providers of articles


@router.get("")
async def get_feed(db: Session = Depends(get_db)):
    """Get general feed"""
    # Query clusters and eagerly load their articles
    clusters = (
        db.query(Cluster)
        .join(Article)
        .options(sqlalchemy.orm.subqueryload(Cluster.articles))
        .all()
    )
    news_providers = db.query(NewsProvider).all()
    rank_map = {np.key: np.rank for np in news_providers if np.rank is not None}
    max_rank: int = max(rank_map.values())

    max_cluster_size = max(len(cluster.articles) for cluster in clusters)

    def score(cluster: Cluster) -> float:
        count = len(cluster.articles)
        avg_timestamp = average_date(
            [article.published_at for article in cluster.articles]
        )
        age_in_hours = (datetime.now().timestamp() - avg_timestamp) / 3600
        size_score = min(len(cluster.articles) / max_cluster_size, 1.0)
        recency_score = math.exp(-age_in_hours)

        avg_rank = (
            sum(rank_map[article.news_provider_key] for article in cluster.articles)
            / count
        )
        rank_score = 1 - min(avg_rank / max_rank, 1.0)

        # Weighted average
        final_score = 0.4 * size_score + 0.3 * recency_score + 0.3 * rank_score
        return round(final_score, 4)

    clusters.sort(key=score, reverse=True)
    clusters = clusters[:20]

    return [
        {
            "id": cluster.id,
            "title": getattr(cluster, "title", None),
            "most_recent_article_date": max(
                article.published_at for article in cluster.articles
            ),
            "avg_rank": sum(
                rank_map[article.news_provider_key] for article in cluster.articles
            )
            / len(cluster.articles),
            "articles": [
                {
                    "id": article.id,
                    "title": getattr(article, "title", None),
                    "published_at": getattr(article, "published_at", None),
                    "news_provider_key": getattr(article, "news_provider_key", None),
                    "url": getattr(article, "url", None),
                    # Add more fields as needed
                }
                for article in getattr(cluster, "articles", [])
            ],
        }
        for cluster in clusters
    ]


@router.get("/{category}")
async def get_feed_by_category(category: str, db: Session = Depends(get_db)):
    """Get feed by category."""
    # TODO: Implement category-specific feed retrieval logic
    # articles = db.query(Article).filter_by(category=category).order_by(Article.published_at.desc()).limit(50).all()
    # return articles

    raise HTTPException(
        status_code=501, detail=f"Feed for category {category} endpoint not implemented"
    )

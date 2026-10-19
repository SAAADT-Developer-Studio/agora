"""
Repository pattern implementation for database operations.
Separates concerns and provides clean abstractions for each entity.
"""

from abc import ABC, abstractmethod  # in case we want to define the repository interface later
from sqlalchemy import exists, func, or_, select, text, update
from sqlalchemy.orm import Session, selectinload, load_only
from .schema import (
    CLUSTER_V2_NEEDS_RANKING_EXPIRY,
    Article,
    NewsProvider,
    Cluster,
    ClusterRun,
    ArticleCluster,
    ClusterV2,
    Story,
    StoryArticle,
    StorySummary,
)
from datetime import datetime
from typing import NamedTuple, Sequence


class ArticleRepository:
    """Repository for Article entity operations."""

    def __init__(self, session: Session):
        self.session = session

    def get_by_urls(self, urls: list[str]) -> set[str]:
        """Get URLs that already exist in the database."""
        query_results = self.session.query(Article.url).filter(Article.url.in_(urls)).all()
        return {result[0] for result in query_results}

    def bulk_create(self, articles: list[Article]) -> None:
        """Bulk insert articles."""
        self.session.add_all(articles)

    def get_clustered_and_pad_articles(self) -> Sequence[Article]:
        clustered = select(Article).where(Article.cluster_id.is_not(None)).cte(name="clustered")

        clustered_cnt_sq = select(func.count()).select_from(clustered).scalar_subquery()

        pad = (
            select(Article)
            .where(Article.cluster_id.is_(None))
            .order_by(Article.published_at.desc())
            .limit(func.greatest(0, 2000 - clustered_cnt_sq))
            .cte(name="pad")
        )

        query = select(clustered).union_all(select(pad))
        stmt = select(Article).from_statement(query)
        result = self.session.scalars(stmt).all()
        return result

    def get_latest(
        self, count: int | None, *, since: datetime | None = None, through: datetime | None = None,
    ) -> Sequence[Article]:
        query = select(Article).order_by(Article.published_at.desc()).limit(count)
        if since is not None:
            query = query.where(Article.published_at >= since)
        if through is not None:
            query = query.where(Article.published_at <= through)
        return self.session.scalars(query).all()

    def get_all_since(self, from_date: datetime) -> Sequence[Article]:
        # limit to 3000 just in case
        return self.session.scalars(
            select(Article)
            .where(Article.published_at > from_date)
            .order_by(Article.published_at.desc())
            .options(load_only(Article.id, Article.title, Article.embedding, Article.published_at))
            .limit(3000)
        ).all()


class NewsProviderRepository:
    """Repository for NewsProvider entity operations."""

    def __init__(self, session: Session):
        self.session = session

    def get_existing_keys(self) -> set[str]:
        """Get all existing provider keys."""
        return {key for (key,) in self.session.query(NewsProvider.key).all()}

    def get_by_key(self, key: str) -> NewsProvider | None:
        """Get news provider by key."""
        return self.session.query(NewsProvider).filter(NewsProvider.key == key).first()

    def get_by_keys(self, keys: list[str]) -> list[NewsProvider]:
        """Get news providers by keys."""
        return self.session.query(NewsProvider).filter(NewsProvider.key.in_(keys)).all()

    def bulk_create(self, providers: list[NewsProvider]) -> None:
        """Bulk insert news providers."""
        self.session.bulk_save_objects(providers)  # TODO: use add_all for consistency

    def create(self, provider: NewsProvider) -> NewsProvider:
        """Create a single news provider."""
        self.session.add(provider)
        return provider

    def update(self, provider: NewsProvider) -> NewsProvider:
        """Update a news provider (already tracked by session)."""
        return provider


class ClusterRepository:
    """Repository for Cluster entity operations."""

    def __init__(self, session: Session):
        self.session = session

    def get_all_nonempty(self) -> Sequence[Cluster]:
        """Get all clusters that have at least one article."""
        # i don't think this works fully?
        stmt = select(Cluster).join(Article, Cluster.id == Article.cluster_id).group_by(Cluster.id)
        return self.session.scalars(stmt).all()


def expired_ranking_statement(
    *, before: datetime, keep_run_id: int | None, after_id: int = 0, limit: int = 100,
):
    """Select one page of clusters whose ranking data should be zeroed.

    The kept production run is never touched. Every other run is cleared when
    its snapshot is older than ``before`` or it already carries a score.
    ``created_at == before`` is not old enough. Rows that already store the
    expired sentinel (score 0 and status "expired") are skipped.

    ``CLUSTER_V2_NEEDS_RANKING_EXPIRY`` is inlined, parenthesized SQL rather
    than bound parameters. It has to match ``ix_cluster_v2_needs_ranking_expiry``
    exactly: ``IS DISTINCT FROM $1`` does not prove the partial index, and a
    generic plan then walks ``cluster_v2_pkey`` from ``id > after_id`` until
    it has skipped every already-expired row.

    The age-or-score condition stays one residual filter on that index. An
    ``ORDER BY id LIMIT`` there stops after one page of non-expired rows.
    Splitting the OR into a UNION makes the scored branch walk older
    non-expired ids it does not return.
    """
    if limit < 1:
        raise ValueError("limit must be positive")
    # Parentheses are part of the constant. AND binds tighter than OR, so an
    # ungrouped predicate would apply the rest of the filter to only one branch.
    statement = (
        select(ClusterV2)
        .where(text(CLUSTER_V2_NEEDS_RANKING_EXPIRY))
        .where(ClusterV2.id > after_id)
    )
    if keep_run_id is None:
        statement = statement.where(ClusterV2.created_at < before)
    else:
        statement = statement.where(
            ClusterV2.run_id != keep_run_id,
            or_(ClusterV2.created_at < before, ClusterV2.rank_score.is_not(None)),
        )
    return (
        statement
        .order_by(ClusterV2.id)
        .limit(limit)
        .options(load_only(ClusterV2.id, ClusterV2.created_at, ClusterV2.run_id))
    )


class ClusterV2Repository:
    """Repository for ClusterV2 entity operations."""

    def __init__(self, session: Session):
        self.session = session

    def bulk_create(self, clusters: list[ClusterV2]) -> None:
        """Bulk insert clusters."""
        self.session.add_all(clusters)

    def get_ranking_batch(
        self, *, run_id: int, after_id: int = 0, limit: int = 100,
    ) -> Sequence[ClusterV2]:
        """Page one clustering run, retaining each member's article history."""
        if limit < 1:
            raise ValueError("limit must be positive")
        return self.session.scalars(
            select(ClusterV2)
            .where(ClusterV2.run_id == run_id, ClusterV2.id > after_id)
            .order_by(ClusterV2.id)
            .limit(limit)
            .options(
                # Previous explanations can be large; scoring replaces them.
                load_only(ClusterV2.id, ClusterV2.run_id, ClusterV2.created_at),
                selectinload(ClusterV2.memberships)
                .selectinload(ArticleCluster.article)
                .load_only(
                    Article.id, Article.title, Article.published_at, Article.first_seen_at,
                    Article.summary, Article.content, Article.categories, Article.llm_rank,
                    Article.embedding, Article.news_provider_key,
                )
                .selectinload(Article.news_provider)
                .load_only(NewsProvider.key, NewsProvider.rank)
            )
        ).all()


    def get_expired_ranking_batch(
        self, *, before: datetime, keep_run_id: int | None, after_id: int = 0, limit: int = 100,
    ) -> Sequence[ClusterV2]:
        """One page of clusters whose ranking data should be zeroed.

        The caller commits each page. Keyset paging by id keeps a failed page
        from retrying rows the previous page already expired.
        """
        return self.session.scalars(
            expired_ranking_statement(
                before=before, keep_run_id=keep_run_id, after_id=after_id, limit=limit,
            )
        ).all()


class ClusterRunRepository:
    """Repository for ClusterRun entity operations."""

    def __init__(self, session: Session):
        self.session = session

    def create(self, cluster_run: ClusterRun) -> None:
        """Create a new cluster run."""
        self.session.add(cluster_run)

    def get_latest_production_id(self) -> int | None:
        """Newest production clustering run. Ties break toward the higher id."""
        return self.session.scalar(
            select(ClusterRun.id)
            .where(ClusterRun.is_production.is_(True))
            .order_by(ClusterRun.created_at.desc(), ClusterRun.id.desc())
            .limit(1)
        )

    def get_latest(self) -> ClusterRun | None:
        """Get the latest cluster run."""
        return self.session.scalars(
            select(ClusterRun)
            .options(
                selectinload(ClusterRun.clusters)
                .selectinload(ClusterV2.memberships)
                .selectinload(ArticleCluster.article)
                .load_only(Article.id, Article.title, Article.embedding, Article.published_at)
            )
            .order_by(ClusterRun.created_at.desc())
            .limit(1)
        ).first()


class AssignedArticle(NamedTuple):
    article_id: int
    story_id: int
    embedding: list[float]
    title: str
    summary: str | None
    published_at: datetime
    method: str


class StoryMemberText(NamedTuple):
    article_id: int
    title: str
    deck: str | None
    summary: str | None
    published_at: datetime


class StoryRepository:
    def __init__(self, session: Session):
        self.session = session

    def get_assigned_since(self, since: datetime) -> Sequence[AssignedArticle]:
        stmt = (
            select(
                Article.id,
                StoryArticle.story_id,
                Article.embedding,
                Article.title,
                Article.summary,
                Article.published_at,
                StoryArticle.method,
            )
            .join(StoryArticle, StoryArticle.article_id == Article.id)
            .where(Article.published_at > since)
        )
        return [AssignedArticle(*row) for row in self.session.execute(stmt).tuples().all()]

    def get_unassigned_since(self, since: datetime, limit: int = 3000) -> Sequence[Article]:
        return self.session.scalars(
            select(Article)
            .where(Article.published_at > since)
            .where(~exists(select(StoryArticle.id).where(StoryArticle.article_id == Article.id)))
            .order_by(Article.published_at.asc())
            .options(
                load_only(
                    Article.id,
                    Article.title,
                    Article.summary,
                    Article.embedding,
                    Article.published_at,
                )
            )
            .limit(limit)
        ).all()

    def get_by_ids(self, story_ids: list[int]) -> dict[int, Story]:
        if not story_ids:
            return {}
        stories = self.session.scalars(select(Story).where(Story.id.in_(story_ids))).all()
        return {story.id: story for story in stories}

    def create(self, story: Story) -> None:
        self.session.add(story)

    def add_membership(self, membership: StoryArticle) -> None:
        self.session.add(membership)

    def member_texts(self, story_id: int) -> Sequence[StoryMemberText]:
        """Every article in the story, earliest published first."""
        stmt = (
            select(
                Article.id,
                Article.title,
                Article.deck,
                Article.summary,
                Article.published_at,
            )
            .join(StoryArticle, StoryArticle.article_id == Article.id)
            .where(StoryArticle.story_id == story_id)
            .order_by(Article.published_at.asc(), Article.id.asc())
        )
        return [StoryMemberText(*row) for row in self.session.execute(stmt).tuples().all()]

    def latest_summary(self, story_id: int) -> StorySummary | None:
        return self.session.scalars(
            select(StorySummary)
            .where(StorySummary.story_id == story_id)
            .order_by(StorySummary.id.desc())
            .limit(1)
        ).first()

    def latest_summaries(self, story_ids: list[int]) -> dict[int, StorySummary]:
        if not story_ids:
            return {}
        rows = self.session.scalars(
            select(StorySummary)
            .where(StorySummary.story_id.in_(story_ids))
            .distinct(StorySummary.story_id)
            .order_by(StorySummary.story_id, StorySummary.id.desc())
        ).all()
        return {row.story_id: row for row in rows}

    def add_summary(self, summary: StorySummary) -> None:
        self.session.add(summary)

    def merge(self, drop: Story, keep: Story) -> None:
        """Move every article of ``drop`` into ``keep``."""
        self.session.flush()
        self.session.execute(
            update(StoryArticle)
            .where(StoryArticle.story_id == drop.id)
            .values(story_id=keep.id)
        )
        drop.merged_into_story_id = keep.id
        if drop.last_article_published_at > keep.last_article_published_at:
            keep.last_article_published_at = drop.last_article_published_at
        self.session.expire(drop, ["memberships"])
        self.session.expire(keep, ["memberships"])

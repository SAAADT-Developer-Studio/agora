from datetime import datetime, timezone
from typing import Optional, List
from sqlalchemy import (
    create_engine,
    String,
    Float,
    Integer,
    DateTime,
    ForeignKey,
    Boolean,
    UniqueConstraint,
    CheckConstraint,
    Enum,
    Index,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import (
    sessionmaker,
    DeclarativeBase,
    Mapped,
    mapped_column,
    relationship,
    MappedAsDataclass,
)
from sqlalchemy.dialects.postgresql import ARRAY, UUID
import os
import uuid
import enum
import dotenv

dotenv.load_dotenv(dotenv.find_dotenv())


class Base(MappedAsDataclass, DeclarativeBase):
    pass


class Article(Base):
    __tablename__ = "article"

    id: Mapped[int] = mapped_column(primary_key=True, init=False)
    url: Mapped[str] = mapped_column(String, unique=True)
    title: Mapped[str] = mapped_column(String)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    deck: Mapped[Optional[str]] = mapped_column(String)
    summary: Mapped[Optional[str]] = mapped_column(String)
    author: Mapped[Optional[str]] = mapped_column(String)
    content: Mapped[Optional[str]] = mapped_column(String)
    embedding: Mapped[List[float]] = mapped_column(ARRAY(Float))
    image_urls: Mapped[Optional[List[str]]] = mapped_column(ARRAY(String))
    categories: Mapped[Optional[List[str]]] = mapped_column(ARRAY(String))
    llm_rank: Mapped[Optional[int]] = mapped_column(Integer)
    is_paywalled: Mapped[Optional[bool]] = mapped_column(Boolean)

    news_provider_key: Mapped[str] = mapped_column(String, ForeignKey("news_provider.key"))
    # Unknown for historical rows; the scraper records discovery time for new articles.
    first_seen_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), default=None
    )
    news_provider: Mapped["NewsProvider"] = relationship(
        "NewsProvider", back_populates="articles", init=False
    )

    cluster_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("cluster.id", ondelete="SET NULL"), init=False
    )
    cluster: Mapped[Optional["Cluster"]] = relationship(
        "Cluster", back_populates="articles", init=False
    )

    cluster_assignments: Mapped[List["ArticleCluster"]] = relationship(
        "ArticleCluster", back_populates="article", cascade="all, delete-orphan", init=False
    )

    social_post_links: Mapped[List["ArticleSocialPost"]] = relationship(
        "ArticleSocialPost", back_populates="article", cascade="all, delete-orphan", init=False
    )

    story_memberships: Mapped[List["StoryArticle"]] = relationship(
        "StoryArticle",
        back_populates="article",
        cascade="all, delete-orphan",
        foreign_keys="StoryArticle.article_id",
        init=False,
    )

    __table_args__ = (
        Index("ix_article_published_at_news_provider_key", "published_at", "news_provider_key"),
    )

    def __repr__(self):
        return f"<Article(id={self.id}, url={self.url}, title={self.title})>"


class NewsProvider(Base):
    __tablename__ = "news_provider"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, unique=True)
    url: Mapped[str] = mapped_column(String, unique=True)
    rank: Mapped[int] = mapped_column(Integer)
    bias_rating: Mapped[Optional[str]] = mapped_column(String)

    articles: Mapped[List["Article"]] = relationship(
        "Article", back_populates="news_provider", init=False
    )
    votes: Mapped[List["Vote"]] = relationship("Vote", back_populates="news_provider", init=False)
    moss_data: Mapped[List["MossData"]] = relationship(
        "MossData", back_populates="provider", init=False
    )

    def __repr__(self):
        return f"<NewsProvider(key={self.key}, name={self.name}, url={self.url}, rank={self.rank})>"


class ClusterRun(Base):
    __tablename__ = "cluster_run"

    id: Mapped[int] = mapped_column(primary_key=True, init=False)
    algo_version: Mapped[str] = mapped_column(String)
    params: Mapped[Optional[dict]] = mapped_column(JSONB)
    is_production: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default_factory=lambda: datetime.now(timezone.utc), init=False
    )

    clusters: Mapped[List["ClusterV2"]] = relationship(
        "ClusterV2", back_populates="run", init=False
    )

    __table_args__ = (Index("ix_cluster_run_created_at", "created_at"),)

    def __repr__(self):
        return f"<ClusterRun(id={self.id}, created_at={self.created_at}, algo_version={self.algo_version}, is_production={self.is_production})>"


class Cluster(Base):
    __tablename__ = "cluster"

    id: Mapped[int] = mapped_column(primary_key=True, init=False)
    title: Mapped[str] = mapped_column(String)
    slug: Mapped[Optional[str]] = mapped_column(String, unique=True)

    articles: Mapped[List["Article"]] = relationship(
        "Article", back_populates="cluster", passive_deletes=True, init=False
    )

    def __repr__(self):
        return f"<Cluster(id={self.id}, title={self.title}, slug={self.slug})>"


class RankingRun(Base):
    __tablename__ = "ranking_run"

    id: Mapped[int] = mapped_column(primary_key=True, init=False)
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    window_days: Mapped[int] = mapped_column(Integer)
    algorithm_version: Mapped[str] = mapped_column(String)
    config: Mapped[dict] = mapped_column(JSONB)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default_factory=lambda: datetime.now(timezone.utc)
    )
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), default=None)
    status: Mapped[str] = mapped_column(String, default="running")
    scored_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    expired_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    skipped_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    failed_cluster_id: Mapped[Optional[int]] = mapped_column(Integer, default=None)
    error: Mapped[Optional[str]] = mapped_column(String, default=None)
    # Historical rows scored HDBSCAN snapshots. Story observations set "story".
    # The server default labels rows that already existed when the column was added.
    source: Mapped[str] = mapped_column(
        String, default="cluster", server_default=text("'cluster'")
    )
    failed_story_id: Mapped[Optional[int]] = mapped_column(Integer, default=None)

    __table_args__ = (
        Index("ix_ranking_run_started_at", "started_at"),
        CheckConstraint(
            "status IN ('running', 'succeeded', 'failed', 'interrupted')",
            name="ck_ranking_run_status",
        ),
        CheckConstraint("window_days > 0", name="ck_ranking_run_window_days"),
        CheckConstraint(
            "scored_count >= 0 AND expired_count >= 0 AND skipped_count >= 0",
            name="ck_ranking_run_counts",
        ),
        CheckConstraint(
            "source IN ('cluster', 'story')",
            name="ck_ranking_run_source",
        ),
    )


class StoryRank(Base):
    """Observation-only score for one story in one ranking run.

    Keyed by the run and the story so a later run appends a new row. Nothing
    in the feed, the clusterer, or the story row reads this table.
    """

    __tablename__ = "story_rank"

    ranking_run_id: Mapped[int] = mapped_column(
        ForeignKey(
            "ranking_run.id", ondelete="CASCADE", name="story_rank_ranking_run_id_fkey",
        ),
        primary_key=True,
    )
    story_id: Mapped[int] = mapped_column(
        ForeignKey("story.id", ondelete="CASCADE", name="story_rank_story_id_fkey"),
        primary_key=True,
    )
    score: Mapped[float] = mapped_column(Float)
    ranked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    rank_version: Mapped[str] = mapped_column(String)
    rank_components: Mapped[dict] = mapped_column(JSONB)
    rank_category: Mapped[Optional[str]] = mapped_column(String, default=None)

    __table_args__ = (
        CheckConstraint("score BETWEEN 0 AND 1", name="ck_story_rank_score"),
        Index("ix_story_rank_story_id", "story_id"),
    )


# Clusters the ranking expiry sweep still has to visit. A stored 0 with
# status "expired" is the sentinel and is left out; NULL score or status is
# not that sentinel (IS DISTINCT FROM). The sweep's WHERE clause must use
# this exact parenthesized text: a bind parameter in its place makes a
# generic plan ignore the partial index and walk cluster_v2_pkey.
CLUSTER_V2_NEEDS_RANKING_EXPIRY = (
    "(rank_score IS DISTINCT FROM 0 "
    "OR (rank_components ->> 'status') IS DISTINCT FROM 'expired')"
)


class ClusterV2(Base):
    __tablename__ = "cluster_v2"

    id: Mapped[int] = mapped_column(primary_key=True, init=False)
    title: Mapped[str] = mapped_column(String)
    slug: Mapped[Optional[str]] = mapped_column(String, unique=True)

    run_id: Mapped[int] = mapped_column(ForeignKey("cluster_run.id", ondelete="CASCADE"))
    rank_score: Mapped[Optional[float]] = mapped_column(Float, default=None)
    ranked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), default=None)
    rank_components: Mapped[Optional[dict]] = mapped_column(JSONB, default=None)
    rank_version: Mapped[Optional[str]] = mapped_column(String, default=None)
    rank_category: Mapped[Optional[str]] = mapped_column(String, default=None)
    ranking_run_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("ranking_run.id", ondelete="SET NULL", name="fk_cluster_v2_ranking_run_id"),
        default=None,
    )
    wiki_image_urls: Mapped[List[str]] = mapped_column(
        ARRAY(String),
        default_factory=list,
        server_default=text("'{}'::character varying[]"),
    )
    wiki_image_metadata: Mapped[List[dict[str, object]]] = mapped_column(
        JSONB,
        default_factory=list,
        server_default=text("'[]'::jsonb"),
    )
    wiki_image_lookup_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        default=None,
    )
    wiki_image_last_attempt_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        default=None,
    )
    run: Mapped["ClusterRun"] = relationship("ClusterRun", back_populates="clusters", init=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default_factory=lambda: datetime.now(timezone.utc), init=False
    )

    # New: historical assignments
    memberships: Mapped[List["ArticleCluster"]] = relationship(
        "ArticleCluster",
        back_populates="cluster",
        cascade="all, delete-orphan",
        init=False,
    )

    __table_args__ = (
        Index("ix_cluster_v2_run_id", "run_id"),
        Index("ix_cluster_v2_created_at_id", "created_at", "id"),
        Index("ix_cluster_v2_ranking_run_id", "ranking_run_id"),
        # id order, only rows the sweep can still return. Expired history
        # stays in the table and out of this index.
        Index(
            "ix_cluster_v2_needs_ranking_expiry",
            "id",
            postgresql_where=text(CLUSTER_V2_NEEDS_RANKING_EXPIRY),
        ),
        CheckConstraint("rank_score BETWEEN 0 AND 1", name="ck_cluster_v2_rank_score"),
    )

    def __repr__(self):
        return f"<ClusterV2(id={self.id}, title={self.title}, slug={self.slug})>"


class ArticleCluster(Base):
    __tablename__ = "article_cluster"

    id: Mapped[int] = mapped_column(primary_key=True, init=False)
    article_id: Mapped[int] = mapped_column(ForeignKey("article.id", ondelete="CASCADE"))
    cluster_id: Mapped[int] = mapped_column(ForeignKey("cluster_v2.id", ondelete="CASCADE"))
    run_id: Mapped[int] = mapped_column(ForeignKey("cluster_run.id", ondelete="CASCADE"))
    membership_confidence: Mapped[Optional[float]] = mapped_column(Float, default=None)

    article: Mapped["Article"] = relationship(
        "Article", back_populates="cluster_assignments", init=False
    )
    cluster: Mapped["ClusterV2"] = relationship(
        "ClusterV2", back_populates="memberships", init=False
    )
    run: Mapped["ClusterRun"] = relationship("ClusterRun", init=False)

    __table_args__ = (
        # Enforce ≤1 primary assignment per article per run
        # via a partial unique index in Alembic (see migration).
        UniqueConstraint("article_id", "cluster_id", "run_id", name="uq_article_cluster_run"),
        CheckConstraint(
            "membership_confidence BETWEEN 0 AND 1",
            name="ck_article_cluster_membership_confidence",
        ),
        Index("ix_article_cluster_cluster_id", "cluster_id"),
        Index("ix_article_cluster_run_id", "run_id"),
    )

    def __repr__(self):
        return f"<ArticleCluster(id={self.id}, article_id={self.article_id}, cluster_id={self.cluster_id}, run_id={self.run_id})>"


class Vote(Base):
    __tablename__ = "vote"
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    provider_id: Mapped[str] = mapped_column(
        String, ForeignKey("news_provider.key"), primary_key=True
    )
    value: Mapped[str] = mapped_column(
        String
    )  # "left", "center left", "center", "center right", "right"
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.now, init=False
    )

    news_provider: Mapped["NewsProvider"] = relationship(
        "NewsProvider", back_populates="votes", init=False
    )

    def __repr__(self):
        return f"<Vote(user_id={self.user_id}, provider_id={self.provider_id}, value={self.value})>"


class MossData(Base):
    __tablename__ = "moss_data"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    provider_key: Mapped[str] = mapped_column(String, ForeignKey("news_provider.key"))
    provider: Mapped["NewsProvider"] = relationship("NewsProvider", back_populates="moss_data", init=False)

    rank: Mapped[int] = mapped_column(Integer)
    website: Mapped[str] = mapped_column(String)
    publisher: Mapped[str] = mapped_column(String)
    reach: Mapped[int] = mapped_column(Integer)
    reach_percent: Mapped[float] = mapped_column(Float)
    avg_daily_reach: Mapped[int] = mapped_column(Integer)
    views: Mapped[int] = mapped_column(Integer)
    avg_session_duration: Mapped[str] = mapped_column(String)
    trend: Mapped[float] = mapped_column(Float)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.now, init=False
    )

    def __repr__(self):
        return f"<MossData(id={self.id}, provider_key={self.provider_key}, website={self.website})>"


class Story(Base):
    __tablename__ = "story"

    id: Mapped[int] = mapped_column(primary_key=True, init=False)
    # Title of the newest story_summary row. Until one exists, the earliest
    # article's title.
    title: Mapped[str] = mapped_column(String)
    last_article_published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.now, init=False
    )
    # Set when the story was found to duplicate another and its articles moved
    # there. A merged story has no memberships; its URL should redirect.
    merged_into_story_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("story.id", ondelete="SET NULL"), default=None
    )

    memberships: Mapped[List["StoryArticle"]] = relationship(
        "StoryArticle",
        back_populates="story",
        cascade="all, delete-orphan",
        init=False,
    )

    __table_args__ = (Index("ix_story_last_article_published_at", "last_article_published_at"),)

    def __repr__(self):
        return f"<Story(id={self.id}, title={self.title})>"


class StorySummary(Base):
    """Generated headline and key-point bullets for a story.

    Append-only: the newest row per story is current, older rows are history.
    """

    __tablename__ = "story_summary"

    id: Mapped[int] = mapped_column(primary_key=True, init=False)
    story_id: Mapped[int] = mapped_column(ForeignKey("story.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String)
    # [{"text": str, "article_ids": [int, ...]}], most important first.
    bullets: Mapped[List[dict]] = mapped_column(JSONB)
    # Earliest published article when this row was written. An earlier article
    # joining the story triggers a new summary.
    lead_article_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("article.id", ondelete="SET NULL")
    )
    model: Mapped[str] = mapped_column(String)
    prompt_version: Mapped[int] = mapped_column(Integer)
    # Later: a nullable `framing` JSONB with what left / center / right outlets
    # (news_provider.bias_rating) emphasize. Only worth generating once at least
    # two bias groups each cover the story with a few articles; with today's
    # provider mix one right-leaning article would speak for the whole side.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default_factory=lambda: datetime.now(timezone.utc), init=False
    )

    __table_args__ = (Index("ix_story_summary_story_id_id", "story_id", "id"),)

    def __repr__(self):
        return f"<StorySummary(id={self.id}, story_id={self.story_id}, title={self.title})>"


class StoryArticle(Base):
    __tablename__ = "story_article"

    id: Mapped[int] = mapped_column(primary_key=True, init=False)
    story_id: Mapped[int] = mapped_column(ForeignKey("story.id", ondelete="CASCADE"))
    article_id: Mapped[int] = mapped_column(ForeignKey("article.id", ondelete="CASCADE"))
    method: Mapped[str] = mapped_column(String)
    similarity: Mapped[Optional[float]] = mapped_column(Float, default=None)
    # Cosine to the story centroid at assignment time.
    story_similarity: Mapped[Optional[float]] = mapped_column(Float, default=None)
    nearest_article_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("article.id", ondelete="SET NULL"), default=None
    )
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.now, init=False
    )

    story: Mapped["Story"] = relationship("Story", back_populates="memberships", init=False)
    article: Mapped["Article"] = relationship(
        "Article", back_populates="story_memberships", foreign_keys=[article_id], init=False
    )

    __table_args__ = (
        UniqueConstraint("article_id", name="uq_story_article_article_id"),
        Index("ix_story_article_story_id", "story_id"),
    )

    def __repr__(self):
        return (
            f"<StoryArticle(id={self.id}, story_id={self.story_id}, article_id={self.article_id})>"
        )


class SocialPlatform(str, enum.Enum):
    """Enum for social media platforms"""

    REDDIT = "reddit"
    # TWITTER = "twitter"
    # FACEBOOK = "facebook"
    # Add more platforms as needed


class SocialPost(Base):
    __tablename__ = "social_post"

    id: Mapped[int] = mapped_column(primary_key=True, init=False)
    platform: Mapped[SocialPlatform] = mapped_column(Enum(SocialPlatform, native_enum=False))
    url: Mapped[str] = mapped_column(String, unique=True)
    posted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True)
    )  # When the post was created
    platform_metadata: Mapped[Optional[dict]] = mapped_column(
        JSONB
    )  # Platform-specific data (subreddit, upvotes, etc.)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.now, init=False
    )

    article_links: Mapped[List["ArticleSocialPost"]] = relationship(
        "ArticleSocialPost", back_populates="social_post", cascade="all, delete-orphan", init=False
    )

    def __repr__(self):
        return f"<SocialPost(id={self.id}, platform={self.platform}, url={self.url})>"


class ArticleSocialPost(Base):
    __tablename__ = "article_social_post"

    id: Mapped[int] = mapped_column(primary_key=True, init=False)
    article_id: Mapped[int] = mapped_column(ForeignKey("article.id", ondelete="CASCADE"))
    social_post_id: Mapped[int] = mapped_column(ForeignKey("social_post.id", ondelete="CASCADE"))

    article: Mapped["Article"] = relationship(
        "Article", back_populates="social_post_links", init=False
    )
    social_post: Mapped["SocialPost"] = relationship(
        "SocialPost", back_populates="article_links", init=False
    )

    __table_args__ = (
        UniqueConstraint("article_id", "social_post_id", name="uq_article_social_post"),
    )

    def __repr__(self):
        return f"<ArticleSocialPost(id={self.id}, article_id={self.article_id}, social_post_id={self.social_post_id})>"


_database_url = os.getenv("DATABASE_URL")
if not _database_url:
    raise ValueError("'DATABASE_URL' environment variable is not set.")

engine = create_engine(_database_url, pool_pre_ping=True)
Session = sessionmaker(bind=engine)

# Tables are managed by Alembic migrations

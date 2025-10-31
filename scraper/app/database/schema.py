from datetime import datetime
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
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import (
    sessionmaker,
    DeclarativeBase,
    Mapped,
    mapped_column,
    relationship,
    MappedAsDataclass,
    DeclarativeBase,
)
from sqlalchemy.dialects.postgresql import ARRAY, UUID
import app.config as config
import uuid


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

    news_provider_key: Mapped[str] = mapped_column(String, ForeignKey("news_provider.key"))
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

    def __repr__(self):
        return f"<NewsProvider(key={self.key}, name={self.name}, url={self.url}, rank={self.rank})>"


class ClusterRun(Base):
    __tablename__ = "cluster_run"

    id: Mapped[int] = mapped_column(primary_key=True, init=False)
    algo_version: Mapped[str] = mapped_column(String)
    params: Mapped[Optional[dict]] = mapped_column(JSONB)
    is_production: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.now, init=False
    )

    clusters: Mapped[List["ClusterV2"]] = relationship(
        "ClusterV2", back_populates="run", init=False
    )

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


class ClusterV2(Base):
    __tablename__ = "cluster_v2"

    id: Mapped[int] = mapped_column(primary_key=True, init=False)
    title: Mapped[str] = mapped_column(String)
    slug: Mapped[Optional[str]] = mapped_column(String, unique=True)

    run_id: Mapped[int] = mapped_column(ForeignKey("cluster_run.id", ondelete="CASCADE"))
    run: Mapped["ClusterRun"] = relationship("ClusterRun", back_populates="clusters", init=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.now, init=False
    )

    # New: historical assignments
    memberships: Mapped[List["ArticleCluster"]] = relationship(
        "ArticleCluster",
        back_populates="cluster",
        cascade="all, delete-orphan",
        init=False,
    )

    def __repr__(self):
        return f"<ClusterV2(id={self.id}, title={self.title}, slug={self.slug})>"


class ArticleCluster(Base):
    __tablename__ = "article_cluster"

    id: Mapped[int] = mapped_column(primary_key=True, init=False)
    article_id: Mapped[int] = mapped_column(ForeignKey("article.id", ondelete="CASCADE"))
    cluster_id: Mapped[int] = mapped_column(ForeignKey("cluster_v2.id", ondelete="CASCADE"))
    run_id: Mapped[int] = mapped_column(ForeignKey("cluster_run.id", ondelete="CASCADE"))

    article: Mapped["Article"] = relationship(
        "Article", back_populates="cluster_assignments", init=False
    )
    cluster: Mapped["ClusterV2"] = relationship(
        "ClusterV2", back_populates="memberships", init=False
    )
    run: Mapped["ClusterRun"] = relationship("ClusterRun", init=False)

    __table_args__ = (
        UniqueConstraint("article_id", "cluster_id", "run_id", name="uq_article_cluster_run"),
        # Enforce ≤1 primary assignment per article per run
        # via a partial unique index in Alembic (see migration).
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


engine = create_engine(config.DATABASE_URL, pool_pre_ping=True)
Session = sessionmaker(bind=engine)

# Tables are managed by Alembic migrations

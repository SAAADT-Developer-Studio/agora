from datetime import datetime
from typing import Optional, List
from sqlalchemy import (
    create_engine,
    String,
    Float,
    Integer,
    DateTime,
    ForeignKey,
)
from sqlalchemy.orm import (
    sessionmaker,
    DeclarativeBase,
    Mapped,
    mapped_column,
    relationship,
    MappedAsDataclass,
)
from sqlalchemy.dialects.postgresql import ARRAY
import app.config as config
from dataclasses import dataclass


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
    llm_rank: Mapped[Optional[int]] = mapped_column(Integer)  # TODO: make this non-nullable later

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

    def __repr__(self):
        return f"<NewsProvider(key={self.key}, name={self.name}, url={self.url}, rank={self.rank})>"


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


engine = create_engine(config.DATABASE_URL, pool_pre_ping=True)
Session = sessionmaker(bind=engine)

# Tables are managed by Alembic migrations

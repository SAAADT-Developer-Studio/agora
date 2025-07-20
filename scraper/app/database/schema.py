from datetime import datetime
from typing import Optional, List
from sqlalchemy import (
    create_engine,
    String,
    Float,
    DateTime,
    ForeignKey,
)
from sqlalchemy.orm import sessionmaker, DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import ARRAY
import app.config as config


class Base(DeclarativeBase):
    pass


class Article(Base):
    __tablename__ = "article"

    id: Mapped[int] = mapped_column(primary_key=True)
    url: Mapped[str] = mapped_column(String, unique=True)
    title: Mapped[str] = mapped_column(String)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    deck: Mapped[Optional[str]] = mapped_column(String)
    summary: Mapped[Optional[str]] = mapped_column(String)
    author: Mapped[Optional[str]] = mapped_column(String)
    content: Mapped[Optional[str]] = mapped_column(String)
    embedding: Mapped[List[float]] = mapped_column(ARRAY(Float))

    news_provider_key: Mapped[str] = mapped_column(String, ForeignKey("news_provider.key"))
    news_provider: Mapped["NewsProvider"] = relationship("NewsProvider", back_populates="articles")

    cluster_id: Mapped[Optional[int]] = mapped_column(ForeignKey("cluster.id", ondelete="SET NULL"))
    cluster: Mapped[Optional["Cluster"]] = relationship("Cluster", back_populates="articles")

    def __repr__(self):
        return f"<Article(id={self.id}, url={self.url}, title={self.title})>"


class NewsProvider(Base):
    __tablename__ = "news_provider"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, unique=True)
    url: Mapped[str] = mapped_column(String, unique=True)

    articles: Mapped[List["Article"]] = relationship("Article", back_populates="news_provider")

    def __repr__(self):
        return f"<NewsProvider(key={self.key}, name={self.name})>"


class Cluster(Base):
    __tablename__ = "cluster"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String)

    articles: Mapped[List["Article"]] = relationship(
        "Article", back_populates="cluster", passive_deletes=True
    )

    def __repr__(self):
        return f"<Cluster(id={self.id}, title={self.title})>"


engine = create_engine(config.DATABASE_URL, pool_pre_ping=True)
Session = sessionmaker(bind=engine)

# Tables are managed by Alembic migrations

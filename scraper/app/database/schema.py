from sqlalchemy import (
    create_engine,
    Column,
    Integer,
    String,
    Float,
    DateTime,
    ForeignKey,
)
from sqlalchemy.orm import sessionmaker, declarative_base, relationship
from sqlalchemy.dialects.postgresql import ARRAY
import app.config as config

Base = declarative_base()


class Article(Base):
    __tablename__ = "article"
    id = Column(Integer, primary_key=True)
    url = Column(String, unique=True, nullable=False)
    title = Column(String)
    published_at = Column(DateTime(timezone=True))
    deck = Column(String)
    summary = Column(String, nullable=True)
    author = Column(String, nullable=True)
    content = Column(String, nullable=True)
    embedding = Column(ARRAY(Float))

    news_provider_key = Column(String, ForeignKey("news_provider.key"), nullable=False)
    news_provider = relationship("NewsProvider", back_populates="articles")

    cluster_id = Column(Integer, ForeignKey("cluster.id"), nullable=True)
    cluster = relationship("Cluster", back_populates="articles")

    def __repr__(self):
        return f"<Article(id={self.id}, url={self.url}, title={self.title})>"


class NewsProvider(Base):
    __tablename__ = "news_provider"
    key = Column(String, primary_key=True, nullable=False)
    name = Column(String, unique=True, nullable=False)
    url = Column(String, unique=True, nullable=False)

    articles = relationship("Article", back_populates="news_provider")

    def __repr__(self):
        return f"<NewsProvider(id={self.id}, name={self.name}, key={self.key})>"


class Cluster(Base):
    __tablename__ = "cluster"
    id = Column(Integer, primary_key=True)
    title = Column(String, nullable=False)

    articles = relationship("Article", back_populates="cluster")

    def __repr__(self):
        return f"<Cluster(id={self.id}, title={self.title})>"


engine = create_engine(config.DATABASE_URL, pool_pre_ping=True)
Session = sessionmaker(bind=engine)

# Tables are managed by Alembic migrations

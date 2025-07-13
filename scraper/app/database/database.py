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


# class Cluster(Base):
#     __tablename__ = "cluster"
#     id = Column(Integer, primary_key=True)
#     title = Column(String, unique=True, nullable=False)

#     def __repr__(self):
#         return f"<Cluster(id={self.id}, name={self.name})>"

engine = create_engine(config.DATABASE_URL, pool_pre_ping=True)
Session = sessionmaker(bind=engine)

# TODO: use https://alembic.sqlalchemy.org/en/latest/ in production
# Create tables
Base.metadata.create_all(engine)


class Database:
    def __init__(self):
        # Create a session
        self.session = Session()

    def close(self):
        self.session.commit()
        self.session.close()

    def get_articls_by_urls(self, urls_to_check: list[str]) -> set[str]:
        query_results = self.session.query(Article.url).filter(Article.url.in_(urls_to_check)).all()
        existing_urls = {result[0] for result in query_results}
        return existing_urls

    def bulk_insert_articles(self, articles: list[Article]):
        self.session.bulk_save_objects(articles)
        self.session.commit()

    def bulk_insert_news_providers(self, providers: list[NewsProvider]):
        self.session.bulk_save_objects(providers)
        self.session.commit()

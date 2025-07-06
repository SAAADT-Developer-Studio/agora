from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.dialects.postgresql import ARRAY
import app.config as config

Base = declarative_base()


class Article(Base):
    __tablename__ = "article"
    id = Column(Integer, primary_key=True)
    url = Column(String, unique=True, nullable=False)
    title = Column(String)
    author = Column(String, nullable=True)
    deck = Column(String)
    content = Column(String, nullable=True)
    published_at = Column(DateTime(timezone=True))
    embedding = Column(ARRAY(Float))

    def __repr__(self):
        return f"<Article(id={self.id}, url={self.url}, title={self.title})>"


# TODO: seed providers
# def seed_new_providers():
#     for provider in PROVIDERS:
#         pass

# class NewsProvider(Base):
#     __tablename__ = "news_provider"
#     id = Column(Integer, primary_key=True)
#     name = Column(String, unique=True, nullable=False)
#     key = Column(String, unique=True, nullable=False)
#     url = Column(String, unique=True, nullable=False)

#     def __repr__(self):
#         return f"<NewsProvider(id={self.id}, name={self.name}, key={self.key})>"


# class Cluster(Base):
#     __tablename__ = "cluster"
#     id = Column(Integer, primary_key=True)
#     title = Column(String, unique=True, nullable=False)

#     def __repr__(self):
#         return f"<Cluster(id={self.id}, name={self.name})>"

engine = create_engine(config.DATABASE_URL)

# TODO: use https://alembic.sqlalchemy.org/en/latest/ in production
# Create tables
Base.metadata.create_all(engine)


class Database:
    def __init__(self):

        # Create a session
        Session = sessionmaker(bind=engine)
        self.session = Session()

    def get_articls_by_urls(self, urls_to_check: list[str]) -> set[str]:
        query_results = (
            self.session.query(Article.url).filter(Article.url.in_(urls_to_check)).all()
        )
        existing_urls = {result[0] for result in query_results}
        return existing_urls

    def bulk_insert_articles(self, articles: list[Article]):
        self.session.bulk_save_objects(articles)

    def close(self):
        self.session.commit()
        self.session.close()

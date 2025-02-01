import os
from sqlmodel import SQLModel, create_engine


def connect_db():
    engine = create_engine(os.getenv("DATABASE_URL", "sqlite:///db.sqlite"))
    SQLModel.metadata.create_all(engine)
    return engine

import uuid
import datetime
from sqlmodel import SQLModel, Field, Column, DateTime, func


class Article(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    created_at: datetime.datetime = Field(default_factory=datetime.datetime.now)
    updated_at: datetime.datetime = Field(
        sa_column=Column(DateTime(), onupdate=func.now())
    )
    url: str = Field(str, unique=True)
    title: str
    summary: str
    content: str
    author: str
    num_comments: int | None = None

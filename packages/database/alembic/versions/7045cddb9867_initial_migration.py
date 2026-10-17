"""initial_migration

Revision ID: 7045cddb9867
Revises: 
Create Date: 2025-07-19 09:50:46.218706

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '7045cddb9867'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    Before Alembic, Base.metadata.create_all() created these two tables, so
    this revision was generated empty. Prod and dev already record it as
    applied and never rerun it. It is filled in so an empty database can be
    built from migrations alone. Constraint names are the PostgreSQL defaults
    create_all() produced.
    """
    op.create_table(
        'news_provider',
        sa.Column('key', sa.String(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('url', sa.String(), nullable=False),
        sa.PrimaryKeyConstraint('key', name='news_provider_pkey'),
        sa.UniqueConstraint('name', name='news_provider_name_key'),
        sa.UniqueConstraint('url', name='news_provider_url_key'),
    )
    op.create_table(
        'article',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('url', sa.String(), nullable=False),
        sa.Column('title', sa.String(), nullable=True),
        sa.Column('published_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('deck', sa.String(), nullable=True),
        sa.Column('summary', sa.String(), nullable=True),
        sa.Column('author', sa.String(), nullable=True),
        sa.Column('content', sa.String(), nullable=True),
        sa.Column('embedding', postgresql.ARRAY(sa.Float()), nullable=True),
        sa.Column('news_provider_key', sa.String(), nullable=False),
        sa.ForeignKeyConstraint(
            ['news_provider_key'],
            ['news_provider.key'],
            name='article_news_provider_key_fkey',
        ),
        sa.PrimaryKeyConstraint('id', name='article_pkey'),
        sa.UniqueConstraint('url', name='article_url_key'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('article')
    op.drop_table('news_provider')

"""add Wikimedia images to cluster_v2

Revision ID: d4a8c21f7e6b
Revises: 479d12d6c013
Create Date: 2026-08-04 18:20:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "d4a8c21f7e6b"
down_revision: Union[str, Sequence[str], None] = "479d12d6c013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "cluster_v2",
        sa.Column(
            "wiki_image_urls",
            postgresql.ARRAY(sa.String()),
            server_default=sa.text("'{}'::character varying[]"),
            nullable=False,
        ),
    )
    op.add_column(
        "cluster_v2",
        sa.Column("wiki_image_lookup_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "cluster_v2",
        sa.Column(
            "wiki_image_last_attempt_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "cluster_v2",
        sa.Column(
            "wiki_image_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("cluster_v2", "wiki_image_last_attempt_at")
    op.drop_column("cluster_v2", "wiki_image_lookup_at")
    op.drop_column("cluster_v2", "wiki_image_metadata")
    op.drop_column("cluster_v2", "wiki_image_urls")

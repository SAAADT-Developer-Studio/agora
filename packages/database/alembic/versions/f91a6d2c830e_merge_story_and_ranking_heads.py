"""Merge the independent story and cluster-ranking migration branches.

Revision ID: f91a6d2c830e
Revises: c8e4f1a92b70, e73b90a4f612
"""

revision = "f91a6d2c830e"
down_revision = ("c8e4f1a92b70", "e73b90a4f612")
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Each parent owns its schema changes; this revision joins their histories.
    pass


def downgrade() -> None:
    pass

"""Keep the default `alembic upgrade head` command unambiguous after merges."""

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
import pytest


@pytest.fixture
def migrations():
    root = Path(__file__).resolve().parents[4]
    return ScriptDirectory.from_config(Config(str(root / "packages/database/alembic.ini")))


def test_migrations_have_one_head(migrations):
    assert len(migrations.get_heads()) == 1


@pytest.mark.parametrize("current,expected,already_applied", [
    ("d4a8c21f7e6b", {"c8e4f1a92b70", "e73b90a4f612"}, set()),
    ("c8e4f1a92b70", {"e73b90a4f612"}, {"c8e4f1a92b70"}),
    ("e73b90a4f612", {"c8e4f1a92b70"}, {"e73b90a4f612"}),
    (("c8e4f1a92b70", "e73b90a4f612"), set(), {"c8e4f1a92b70", "e73b90a4f612"}),
])
def test_upgrade_plan_handles_either_or_both_applied_branches(
    migrations, current, expected, already_applied,
):
    # Match upgrade's traversal: include unapplied sibling branches at a merge.
    pending = {
        revision.revision
        for revision in migrations.iterate_revisions("head", current, implicit_base=True)
    }
    assert expected <= pending
    assert not already_applied & pending
    assert "f91a6d2c830e" in pending

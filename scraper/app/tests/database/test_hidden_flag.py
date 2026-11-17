"""Operator hide flag: a boolean column, a live-safe migration, and merge inheritance."""

from datetime import datetime, timezone
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateColumn

from database.repositories import StoryRepository
from database.schema import ClusterV2, Story


NOW = datetime(2026, 11, 17, tzinfo=timezone.utc)


def test_hidden_defaults_to_false_on_both_tables():
    cluster = ClusterV2(title="Station", slug="station", run_id=1)
    story = Story(title="Station", last_article_published_at=NOW)
    assert cluster.hidden is False
    assert story.hidden is False

    dialect = postgresql.dialect()
    for table in (ClusterV2.__table__, Story.__table__):
        column = table.c.hidden
        assert column.nullable is False
        rendered = str(CreateColumn(column).compile(dialect=dialect))
        assert "BOOLEAN" in rendered
        assert "DEFAULT false" in rendered
        assert "NOT NULL" in rendered


def test_hidden_migration_is_a_constant_default_add_column():
    root = Path(__file__).resolve().parents[4]
    migrations = ScriptDirectory.from_config(Config(str(root / "packages/database/alembic.ini")))
    found = []
    for script in migrations.walk_revisions():
        source = Path(script.path).read_text()
        if "cluster_v2" in source and 'sa.Column(\n            "hidden"' in source:
            found.append((script, source))
    assert len(found) == 1
    script, source = found[0]
    assert script.down_revision == "e4b7c2a81d06"
    assert '"story"' in source
    assert "nullable=False" in source
    assert 'server_default=sa.text("false")' in source
    # A constant default is metadata-only on Postgres 11+. An UPDATE backfill
    # would rewrite the live tables.
    upgrade = source.split("def upgrade", 1)[1].split("def downgrade", 1)[0]
    assert "UPDATE" not in upgrade.upper()
    assert "op.execute" not in upgrade
    assert migrations.get_heads() == [script.revision]


class _Session:
    def flush(self):
        return None

    def execute(self, statement):
        return statement

    def expire(self, obj, attrs):
        return None


def _story(*, hidden: bool) -> Story:
    story = Story(title="Station", last_article_published_at=NOW, hidden=hidden)
    return story


def test_merge_hides_the_survivor_when_either_story_is_hidden():
    repo = StoryRepository(_Session())
    keep = _story(hidden=False)
    drop = _story(hidden=True)
    keep.id = 1
    drop.id = 2
    repo.merge(drop, keep)
    assert keep.hidden is True
    assert drop.merged_into_story_id == 1

    already = _story(hidden=True)
    visible = _story(hidden=False)
    already.id = 3
    visible.id = 4
    repo.merge(visible, already)
    assert already.hidden is True

    left = _story(hidden=False)
    right = _story(hidden=False)
    left.id = 5
    right.id = 6
    repo.merge(right, left)
    assert left.hidden is False

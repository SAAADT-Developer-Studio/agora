from logging.config import fileConfig
import os
import re

from sqlalchemy import engine_from_config
from sqlalchemy import pool

from alembic import context
from database.schema import Base

# Unit is required. PostgreSQL treats a bare number as milliseconds.
_LOCK_TIMEOUT = re.compile(r"^[1-9][0-9]*(ms|s|min|h)$")
_DEFAULT_LOCK_TIMEOUT = "30s"

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def get_url() -> str:
    url = os.getenv("DATABASE_URL")
    if not url:
        raise ValueError("'DATABASE_URL' environment variable is not set.")
    return url


def lock_timeout_setting() -> str | None:
    """PostgreSQL lock_timeout for this migration connection.

    ALEMBIC_LOCK_TIMEOUT overrides the 30s default. 0, off, false, or none
    skips the setting. A blocked ALTER then fails instead of waiting out the
    deploy. statement_timeout is intentionally unset: the ranking index build
    is one statement and must be allowed to finish.
    """
    raw = os.getenv("ALEMBIC_LOCK_TIMEOUT", _DEFAULT_LOCK_TIMEOUT).strip()
    if raw.lower() in {"0", "off", "false", "none"}:
        return None
    if _LOCK_TIMEOUT.fullmatch(raw) is None:
        raise ValueError(
            "ALEMBIC_LOCK_TIMEOUT must be a PostgreSQL interval such as 30s, "
            f"not {raw!r}"
        )
    return raw


def apply_lock_timeout(connection) -> None:
    """Set lock_timeout for PostgreSQL only, before the migration transaction."""
    if connection.dialect.name != "postgresql":
        return
    timeout = lock_timeout_setting()
    if timeout is None:
        return
    # Validated above, so this is a session GUC, not interpolated user SQL.
    connection.exec_driver_sql(f"SET lock_timeout = '{timeout}'")
    connection.commit()


def run_migrations_offline() -> None:
    context.configure(
        url=get_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = get_url()

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        apply_lock_timeout(connection)
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

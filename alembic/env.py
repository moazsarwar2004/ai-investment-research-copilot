"""Alembic environment using the validated async migration connection."""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from backend.app.core.config import Settings
from backend.app.database.base import Base
from backend.app.models import AuditLog, User, UserSession

_MODELS = (AuditLog, User, UserSession)

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

settings = Settings()
config.set_main_option(
    "sqlalchemy.url",
    settings.migration_database_dsn.replace("%", "%%"),
)
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Render SQL without opening a database connection."""
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """Configure migrations on the synchronous facade of the async engine."""
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Open one async connection and execute transactional migrations."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        connect_args={
            "timeout": settings.database_connect_timeout_seconds,
            "command_timeout": settings.database_command_timeout_seconds,
        },
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_async_migrations())

from __future__ import annotations

import asyncio
import os
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import create_engine, pool

from aribot_auth.migrations.schema import metadata

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = metadata


def _db_url() -> str:
    db_path = os.environ.get("ARIBOT_DB")
    if not db_path:
        raise RuntimeError("Missing required environment variable: ARIBOT_DB")
    return f"sqlite:///{db_path}"


def run_migrations_offline() -> None:
    context.configure(
        url=_db_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    def _run_sync() -> None:
        engine = create_engine(_db_url(), poolclass=pool.NullPool)
        with engine.connect() as connection:
            context.configure(connection=connection, target_metadata=target_metadata)
            with context.begin_transaction():
                context.run_migrations()

    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _run_sync)


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

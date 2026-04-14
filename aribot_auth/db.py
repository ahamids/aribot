import asyncio
import os
from pathlib import Path
from typing import AsyncGenerator

import aiosqlite
from alembic import command
from alembic.config import Config

if not os.environ.get("ARIBOT_DB"):
    raise RuntimeError("Missing required environment variable: ARIBOT_DB")

_wal_initialized = False


async def get_db() -> AsyncGenerator[aiosqlite.Connection, None]:
    global _wal_initialized
    db_path = os.environ.get("ARIBOT_DB")
    if not db_path:
        raise RuntimeError("Missing required environment variable: ARIBOT_DB")

    db = await aiosqlite.connect(db_path)
    try:
        db.row_factory = aiosqlite.Row
        if not _wal_initialized:
            await db.execute("PRAGMA journal_mode=WAL")
            _wal_initialized = True
        await db.execute("PRAGMA foreign_keys=ON")
        yield db
    finally:
        await db.close()


def _run_upgrade(db_path: str) -> None:
    here = Path(__file__).resolve().parent
    alembic_ini = here / "migrations" / "alembic.ini"
    cfg = Config(str(alembic_ini))
    cfg.set_main_option("script_location", str(here / "migrations"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    command.upgrade(cfg, "head")


async def run_migrations(db_path: str) -> None:
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _run_upgrade, db_path)

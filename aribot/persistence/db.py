from __future__ import annotations

from pathlib import Path

from migrate_live_schema import run_migration


def run_startup_migrations(db_path: str) -> None:
    """Run idempotent schema migrations before runtime starts."""
    run_migration(Path(db_path))

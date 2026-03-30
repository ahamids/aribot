#!/usr/bin/env python3
"""Idempotent SQLite migration for the live bot schema."""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path


POSITIONS_ADDITIONAL_COLUMNS = {
    "exchange_order_id": "TEXT",
    "avg_fill_price": "REAL",
    "slippage_bps": "REAL",
    "native_sl_active": "INTEGER DEFAULT 0",
    "native_tp_active": "INTEGER DEFAULT 0",
    "native_trail_active": "INTEGER DEFAULT 0",
    "native_sl_price": "REAL",
}


ORDERS_DDL = """
CREATE TABLE IF NOT EXISTS orders (
    id TEXT PRIMARY KEY,
    exchange_order_id TEXT,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    intended_qty REAL NOT NULL,
    filled_qty REAL NOT NULL DEFAULT 0,
    avg_fill_price REAL,
    slippage_bps REAL,
    fee_paid REAL NOT NULL DEFAULT 0,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    filled_at TEXT
);
"""


FILLS_DDL = """
CREATE TABLE IF NOT EXISTS fills (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    price REAL NOT NULL,
    qty REAL NOT NULL,
    fee REAL NOT NULL DEFAULT 0,
    timestamp TEXT NOT NULL,
    FOREIGN KEY(order_id) REFERENCES orders(id)
);
"""


FUNDING_PAYMENTS_DDL = """
CREATE TABLE IF NOT EXISTS funding_payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    rate REAL NOT NULL,
    payment REAL NOT NULL,
    timestamp TEXT NOT NULL
);
"""


KILL_SWITCH_LOG_DDL = """
CREATE TABLE IF NOT EXISTS kill_switch_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trigger_source TEXT NOT NULL,
    positions_closed INTEGER NOT NULL DEFAULT 0,
    reason TEXT NOT NULL,
    timestamp TEXT NOT NULL
);
"""


INDEX_DDLS = [
    # Reconciler lookups by exchange order id and current order state.
    "CREATE INDEX IF NOT EXISTS idx_positions_exchange_order_id ON positions(exchange_order_id);",
    "CREATE INDEX IF NOT EXISTS idx_orders_exchange_order_id ON orders(exchange_order_id);",
    "CREATE INDEX IF NOT EXISTS idx_orders_status_created_at ON orders(status, created_at);",
    # Analytics and symbol-scoped timelines.
    "CREATE INDEX IF NOT EXISTS idx_orders_symbol_created_at ON orders(symbol, created_at);",
    "CREATE INDEX IF NOT EXISTS idx_orders_filled_at ON orders(filled_at);",
    "CREATE INDEX IF NOT EXISTS idx_fills_order_id ON fills(order_id);",
    "CREATE INDEX IF NOT EXISTS idx_fills_symbol_timestamp ON fills(symbol, timestamp);",
    "CREATE INDEX IF NOT EXISTS idx_funding_payments_symbol_timestamp ON funding_payments(symbol, timestamp);",
    "CREATE INDEX IF NOT EXISTS idx_funding_payments_timestamp ON funding_payments(timestamp);",
    "CREATE INDEX IF NOT EXISTS idx_kill_switch_log_timestamp ON kill_switch_log(timestamp);",
    # Existing analytics table recommendations.
    "CREATE INDEX IF NOT EXISTS idx_closed_trades_symbol_close_time ON closed_trades(symbol, close_time);",
    "CREATE INDEX IF NOT EXISTS idx_closed_trades_close_time ON closed_trades(close_time);",
]


def get_columns(cursor: sqlite3.Cursor, table_name: str) -> set[str]:
    rows = cursor.execute(f"PRAGMA table_info({table_name})").fetchall()
    return {row[1] for row in rows}


def table_exists(cursor: sqlite3.Cursor, table_name: str) -> bool:
    row = cursor.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def ensure_positions_columns(cursor: sqlite3.Cursor) -> None:
    existing_columns = get_columns(cursor, "positions")
    for column_name, column_type in POSITIONS_ADDITIONAL_COLUMNS.items():
        if column_name not in existing_columns:
            cursor.execute(f"ALTER TABLE positions ADD COLUMN {column_name} {column_type}")


def migrate_funding_payments(cursor: sqlite3.Cursor) -> None:
    if not table_exists(cursor, "funding_payments"):
        cursor.execute(FUNDING_PAYMENTS_DDL)
        return

    existing_columns = get_columns(cursor, "funding_payments")
    desired_columns = {"id", "symbol", "rate", "payment", "timestamp"}
    if desired_columns.issubset(existing_columns):
        return

    cursor.execute("DROP TABLE IF EXISTS funding_payments_v2")
    cursor.execute(FUNDING_PAYMENTS_DDL.replace("funding_payments", "funding_payments_v2"))

    source_symbol = "symbol" if "symbol" in existing_columns else "NULL"
    source_rate = "rate" if "rate" in existing_columns else "funding_rate"
    if source_rate not in existing_columns:
        source_rate = "0.0"
    source_payment = "payment" if "payment" in existing_columns else "0.0"
    source_timestamp = "timestamp" if "timestamp" in existing_columns else "ts"
    if source_timestamp not in existing_columns:
        source_timestamp = "datetime('now')"

    cursor.execute(
        f"""
        INSERT INTO funding_payments_v2 (id, symbol, rate, payment, timestamp)
        SELECT id, {source_symbol}, {source_rate}, {source_payment}, {source_timestamp}
        FROM funding_payments
        """
    )

    cursor.execute("ALTER TABLE funding_payments RENAME TO funding_payments_legacy")
    cursor.execute("ALTER TABLE funding_payments_v2 RENAME TO funding_payments")


def run_migration(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()

        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA foreign_keys=ON")

        cursor.execute("BEGIN IMMEDIATE")

        ensure_positions_columns(cursor)

        cursor.execute(ORDERS_DDL)
        cursor.execute(FILLS_DDL)
        migrate_funding_payments(cursor)
        cursor.execute(KILL_SWITCH_LOG_DDL)

        for ddl in INDEX_DDLS:
            cursor.execute(ddl)

        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrate SQLite schema for the live trading bot")
    parser.add_argument(
        "--db",
        default="usdt_paper_bot_v2.db",
        help="Path to the SQLite database file",
    )
    args = parser.parse_args()

    run_migration(Path(args.db))
    print(f"Migration completed successfully for {args.db}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
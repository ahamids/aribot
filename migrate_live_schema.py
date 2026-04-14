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
    "native_stops_cancelled_at": "TEXT",
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
    ts TEXT NOT NULL,
    symbol TEXT NOT NULL,
    position_side TEXT NOT NULL,
    position_qty REAL NOT NULL,
    funding_rate REAL NOT NULL,
    mark_price REAL NOT NULL,
    payment REAL NOT NULL,
    run_id TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'estimated'
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
    "CREATE INDEX IF NOT EXISTS idx_funding_payments_symbol_ts ON funding_payments(symbol, ts);",
    "CREATE INDEX IF NOT EXISTS idx_funding_payments_ts ON funding_payments(ts);",
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
    # Skip if positions table doesn't exist yet; engine.py will create it with all columns.
    if not table_exists(cursor, "positions"):
        return
    existing_columns = get_columns(cursor, "positions")
    for column_name, column_type in POSITIONS_ADDITIONAL_COLUMNS.items():
        if column_name not in existing_columns:
            cursor.execute(f"ALTER TABLE positions ADD COLUMN {column_name} {column_type}")


def migrate_funding_payments(cursor: sqlite3.Cursor) -> None:
    if not table_exists(cursor, "funding_payments"):
        cursor.execute(FUNDING_PAYMENTS_DDL)
        return

    existing_columns = get_columns(cursor, "funding_payments")
    desired_columns = {"id", "ts", "symbol", "position_side", "position_qty", "funding_rate", "mark_price", "payment", "run_id", "source"}
    if desired_columns.issubset(existing_columns):
        return

    cursor.execute("DROP TABLE IF EXISTS funding_payments_v2")
    cursor.execute(FUNDING_PAYMENTS_DDL.replace("funding_payments", "funding_payments_v2"))

    source_symbol = "symbol" if "symbol" in existing_columns else "NULL"
    source_ts = "timestamp" if "timestamp" in existing_columns else "datetime('now')"
    source_position_side = "position_side" if "position_side" in existing_columns else "'LONG'"
    source_position_qty = "position_qty" if "position_qty" in existing_columns else "0.0"
    source_funding_rate = "funding_rate" if "funding_rate" in existing_columns else ("rate" if "rate" in existing_columns else "0.0")
    source_mark_price = "mark_price" if "mark_price" in existing_columns else "0.0"
    source_payment = "payment" if "payment" in existing_columns else "0.0"
    source_run_id = "run_id" if "run_id" in existing_columns else "'migration'"
    source_source = "source" if "source" in existing_columns else "'legacy'"

    cursor.execute(
        f"""
        INSERT INTO funding_payments_v2 (id, ts, symbol, position_side, position_qty, funding_rate, mark_price, payment, run_id, source)
        SELECT id, {source_ts}, {source_symbol}, {source_position_side}, {source_position_qty}, {source_funding_rate}, {source_mark_price}, {source_payment}, {source_run_id}, {source_source}
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

        # Create indexes only for tables that exist. Positions table is created by engine.py later.
        for ddl in INDEX_DDLS:
            try:
                cursor.execute(ddl)
            except sqlite3.OperationalError as e:
                # Skip indexes for tables that don't exist yet (e.g., positions created by engine.py)
                if "no such table" not in str(e):
                    raise

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
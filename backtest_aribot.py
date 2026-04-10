#!/usr/bin/env python3
"""Aribot historical pipeline: Bybit backfill + deterministic backtest.

This script is intentionally separate from live bot execution and provides:
1) backfill: fetch Bybit historical 4h candles as far back as each symbol allows.
2) run: execute a deterministic strategy backtest with robust artifacts.

The strategy logic is aligned with usdt_paper_bot_v2.py where practical:
- OHLC4 source, WMA(45, offset=2)
- BTC regime gate via WMA(90, offset=0)
- hard stop -2.5%
- partial exits 2/3/5 with 25/25/25 sizing
- trailing activation at +2% with 1.5% callback
- time exit at 40h
- ATR risk scalar and leverage buckets
"""

from __future__ import annotations

import argparse
import csv
import dataclasses
import datetime as dt
import hashlib
import json
import math
import os
import sqlite3
import sys
import time
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import requests


BYBIT_MAINNET = "https://api.bybit.com"
BYBIT_TESTNET = "https://api-testnet.bybit.com"
DEFAULT_INTERVAL = "240"  # 4h
MS_PER_4H = 4 * 60 * 60 * 1000


@dataclasses.dataclass
class Candle:
    open_time_ms: int
    open_price: float
    high_price: float
    low_price: float
    close_price: float
    volume: float
    turnover: float


@dataclasses.dataclass
class Position:
    symbol: str
    side: str  # long/short
    entry_price: float
    quantity: float
    entry_time_ms: int
    leverage: float
    leverage_tier: str
    round_trip_fee_rate: float
    trailing_stop_active: bool = False
    trailing_stop_level: Optional[float] = None
    peak_pnl_pct: float = 0.0
    partial_exits: Optional[List[dict]] = None

    def __post_init__(self) -> None:
        if self.partial_exits is None:
            self.partial_exits = []


@dataclasses.dataclass
class BacktestConfig:
    initial_balance: float = 400.0
    max_open_positions: int = 10
    entry_risk_pct: float = 0.11
    signal_source: str = "ohlc4"
    signal_wma_period: int = 45
    signal_wma_offset: int = 2
    btc_regime_source: str = "ohlc4"
    btc_regime_wma_period: int = 90
    btc_regime_wma_offset: int = 0
    atr_period: int = 14
    atr_volatility_cutoff: float = 0.05
    atr_size_scalar: float = 0.5
    round_trip_fee_rate: float = 0.0011
    hard_stop_pct: float = 0.025
    trailing_trigger_pct: float = 0.02
    trailing_buffer_pct: float = 0.015
    partial_levels: Tuple[float, ...] = (0.02, 0.03, 0.05)
    partial_sizes: Tuple[float, ...] = (0.25, 0.25, 0.25)
    max_hold_minutes: int = 40 * 60
    daily_drawdown_limit: float = -0.05
    max_consecutive_losses: int = 3
    cooldown_candles: int = 2
    macd_fast_period: int = 2
    macd_slow_period: int = 39
    macd_signal_period: int = 6
    stoch_rsi_period: int = 14
    stoch_rsi_k_period: int = 3
    stoch_rsi_d_period: int = 3
    require_macd_confirmation: bool = False
    require_stoch_rsi_confirmation: bool = False


class SQLiteStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.conn = sqlite3.connect(str(db_path))
        self.conn.row_factory = sqlite3.Row
        self._setup()

    def _setup(self) -> None:
        cur = self.conn.cursor()
        cur.executescript(
            """
            PRAGMA journal_mode = WAL;
            CREATE TABLE IF NOT EXISTS instruments_snapshot (
                snapshot_id TEXT NOT NULL,
                captured_at_utc TEXT NOT NULL,
                category TEXT NOT NULL,
                symbol TEXT NOT NULL,
                status TEXT,
                launch_time_ms INTEGER,
                delivery_time_ms INTEGER,
                base_coin TEXT,
                quote_coin TEXT,
                settle_coin TEXT,
                min_leverage REAL,
                max_leverage REAL,
                leverage_step REAL,
                payload_json TEXT NOT NULL,
                PRIMARY KEY (snapshot_id, symbol)
            );

            CREATE TABLE IF NOT EXISTS candles (
                category TEXT NOT NULL,
                symbol TEXT NOT NULL,
                interval TEXT NOT NULL,
                open_time_ms INTEGER NOT NULL,
                close_time_ms INTEGER NOT NULL,
                open_price REAL NOT NULL,
                high_price REAL NOT NULL,
                low_price REAL NOT NULL,
                close_price REAL NOT NULL,
                volume REAL NOT NULL,
                turnover REAL NOT NULL,
                source_run_id TEXT NOT NULL,
                ingested_at_utc TEXT NOT NULL,
                PRIMARY KEY (category, symbol, interval, open_time_ms)
            );

            CREATE TABLE IF NOT EXISTS ingestion_runs (
                run_id TEXT PRIMARY KEY,
                started_at_utc TEXT NOT NULL,
                finished_at_utc TEXT,
                base_url TEXT NOT NULL,
                category TEXT NOT NULL,
                interval TEXT NOT NULL,
                symbol_count INTEGER NOT NULL,
                request_count INTEGER NOT NULL DEFAULT 0,
                candle_count INTEGER NOT NULL DEFAULT 0,
                notes_json TEXT
            );

            CREATE TABLE IF NOT EXISTS dataset_manifests (
                manifest_id TEXT PRIMARY KEY,
                created_at_utc TEXT NOT NULL,
                run_id TEXT NOT NULL,
                category TEXT NOT NULL,
                interval TEXT NOT NULL,
                start_time_ms INTEGER,
                end_time_ms INTEGER,
                symbol_count INTEGER NOT NULL,
                candle_count INTEGER NOT NULL,
                dataset_sha256 TEXT NOT NULL,
                symbols_json TEXT NOT NULL,
                notes_json TEXT
            );
            """
        )
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def insert_instrument_snapshot(self, snapshot_id: str, captured_at: str, category: str, item: dict) -> None:
        cur = self.conn.cursor()
        lev = item.get("leverageFilter") or {}
        cur.execute(
            """
            INSERT OR REPLACE INTO instruments_snapshot (
                snapshot_id, captured_at_utc, category, symbol, status,
                launch_time_ms, delivery_time_ms, base_coin, quote_coin, settle_coin,
                min_leverage, max_leverage, leverage_step, payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                snapshot_id,
                captured_at,
                category,
                str(item.get("symbol") or "").upper(),
                str(item.get("status") or ""),
                parse_int(item.get("launchTime")),
                parse_int(item.get("deliveryTime")),
                str(item.get("baseCoin") or "").upper(),
                str(item.get("quoteCoin") or "").upper(),
                str(item.get("settleCoin") or "").upper(),
                parse_float(lev.get("minLeverage")),
                parse_float(lev.get("maxLeverage")),
                parse_float(lev.get("leverageStep")),
                json.dumps(item, separators=(",", ":"), sort_keys=True),
            ),
        )

    def upsert_candle(
        self,
        *,
        category: str,
        symbol: str,
        interval: str,
        candle: Candle,
        run_id: str,
        ingested_at_utc: str,
    ) -> None:
        cur = self.conn.cursor()
        cur.execute(
            """
            INSERT INTO candles (
                category, symbol, interval, open_time_ms, close_time_ms,
                open_price, high_price, low_price, close_price,
                volume, turnover, source_run_id, ingested_at_utc
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(category, symbol, interval, open_time_ms) DO UPDATE SET
                close_time_ms=excluded.close_time_ms,
                open_price=excluded.open_price,
                high_price=excluded.high_price,
                low_price=excluded.low_price,
                close_price=excluded.close_price,
                volume=excluded.volume,
                turnover=excluded.turnover,
                source_run_id=excluded.source_run_id,
                ingested_at_utc=excluded.ingested_at_utc
            """,
            (
                category,
                symbol,
                interval,
                candle.open_time_ms,
                candle.open_time_ms + interval_to_ms(interval) - 1,
                candle.open_price,
                candle.high_price,
                candle.low_price,
                candle.close_price,
                candle.volume,
                candle.turnover,
                run_id,
                ingested_at_utc,
            ),
        )

    def fetch_candles(
        self,
        *,
        category: str,
        symbol: str,
        interval: str,
        start_ms: Optional[int],
        end_ms: Optional[int],
    ) -> List[Candle]:
        conditions = ["category = ?", "symbol = ?", "interval = ?"]
        params: List[object] = [category, symbol, interval]
        if start_ms is not None:
            conditions.append("open_time_ms >= ?")
            params.append(start_ms)
        if end_ms is not None:
            conditions.append("open_time_ms <= ?")
            params.append(end_ms)

        sql = (
            "SELECT open_time_ms, open_price, high_price, low_price, close_price, volume, turnover "
            "FROM candles WHERE " + " AND ".join(conditions) + " ORDER BY open_time_ms ASC"
        )
        cur = self.conn.cursor()
        rows = cur.execute(sql, params).fetchall()
        return [
            Candle(
                open_time_ms=int(r["open_time_ms"]),
                open_price=float(r["open_price"]),
                high_price=float(r["high_price"]),
                low_price=float(r["low_price"]),
                close_price=float(r["close_price"]),
                volume=float(r["volume"]),
                turnover=float(r["turnover"]),
            )
            for r in rows
        ]

    def list_symbols_with_candles(self, category: str, interval: str) -> List[str]:
        cur = self.conn.cursor()
        rows = cur.execute(
            "SELECT DISTINCT symbol FROM candles WHERE category = ? AND interval = ? ORDER BY symbol",
            (category, interval),
        ).fetchall()
        return [str(r["symbol"]) for r in rows]

    def record_ingestion_run_start(self, run_id: str, started_at: str, base_url: str, category: str, interval: str, symbol_count: int, notes: dict) -> None:
        cur = self.conn.cursor()
        cur.execute(
            """
            INSERT OR REPLACE INTO ingestion_runs (
                run_id, started_at_utc, base_url, category, interval, symbol_count, request_count, candle_count, notes_json
            ) VALUES (?, ?, ?, ?, ?, ?, 0, 0, ?)
            """,
            (run_id, started_at, base_url, category, interval, symbol_count, json.dumps(notes, separators=(",", ":"), sort_keys=True)),
        )
        self.conn.commit()

    def record_ingestion_run_progress(self, run_id: str, request_count: int, candle_count: int) -> None:
        cur = self.conn.cursor()
        cur.execute(
            "UPDATE ingestion_runs SET request_count = ?, candle_count = ? WHERE run_id = ?",
            (request_count, candle_count, run_id),
        )
        self.conn.commit()

    def record_ingestion_run_end(self, run_id: str, finished_at: str) -> None:
        cur = self.conn.cursor()
        cur.execute("UPDATE ingestion_runs SET finished_at_utc = ? WHERE run_id = ?", (finished_at, run_id))
        self.conn.commit()

    def create_manifest(
        self,
        *,
        run_id: str,
        category: str,
        interval: str,
        start_ms: Optional[int],
        end_ms: Optional[int],
        symbols: List[str],
        notes: dict,
    ) -> dict:
        cur = self.conn.cursor()
        params: List[object] = [category, interval]
        where_parts = ["category = ?", "interval = ?"]
        if start_ms is not None:
            where_parts.append("open_time_ms >= ?")
            params.append(start_ms)
        if end_ms is not None:
            where_parts.append("open_time_ms <= ?")
            params.append(end_ms)
        if symbols:
            placeholders = ",".join("?" for _ in symbols)
            where_parts.append(f"symbol IN ({placeholders})")
            params.extend(symbols)

        count_sql = "SELECT COUNT(*) AS c FROM candles WHERE " + " AND ".join(where_parts)
        row_count = int(cur.execute(count_sql, params).fetchone()["c"])

        hash_sql = (
            "SELECT symbol, open_time_ms, open_price, high_price, low_price, close_price, volume, turnover "
            "FROM candles WHERE " + " AND ".join(where_parts) + " ORDER BY symbol, open_time_ms"
        )
        digest = hashlib.sha256()
        for row in cur.execute(hash_sql, params):
            payload = "|".join(
                [
                    str(row["symbol"]),
                    str(row["open_time_ms"]),
                    f"{float(row['open_price']):.12f}",
                    f"{float(row['high_price']):.12f}",
                    f"{float(row['low_price']):.12f}",
                    f"{float(row['close_price']):.12f}",
                    f"{float(row['volume']):.12f}",
                    f"{float(row['turnover']):.12f}",
                ]
            )
            digest.update(payload.encode("utf-8"))

        manifest_id = f"dataset-{utc_now().strftime('%Y%m%dT%H%M%SZ')}-{digest.hexdigest()[:12]}"
        manifest = {
            "manifest_id": manifest_id,
            "created_at_utc": utc_now().isoformat(),
            "run_id": run_id,
            "category": category,
            "interval": interval,
            "start_time_ms": start_ms,
            "end_time_ms": end_ms,
            "symbol_count": len(symbols),
            "candle_count": row_count,
            "dataset_sha256": digest.hexdigest(),
            "symbols": symbols,
            "notes": notes,
        }

        cur.execute(
            """
            INSERT OR REPLACE INTO dataset_manifests (
                manifest_id, created_at_utc, run_id, category, interval,
                start_time_ms, end_time_ms, symbol_count, candle_count,
                dataset_sha256, symbols_json, notes_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                manifest["manifest_id"],
                manifest["created_at_utc"],
                run_id,
                category,
                interval,
                start_ms,
                end_ms,
                len(symbols),
                row_count,
                manifest["dataset_sha256"],
                json.dumps(symbols, separators=(",", ":"), sort_keys=True),
                json.dumps(notes, separators=(",", ":"), sort_keys=True),
            ),
        )
        self.conn.commit()
        return manifest


class BybitPublicClient:
    def __init__(
        self,
        *,
        base_url: str,
        timeout_seconds: float = 20.0,
        max_retries: int = 8,
        retry_base_seconds: float = 1.0,
        retry_max_seconds: float = 30.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.max_retries = max(0, int(max_retries))
        self.retry_base_seconds = max(0.1, float(retry_base_seconds))
        self.retry_max_seconds = max(self.retry_base_seconds, float(retry_max_seconds))
        self.session = requests.Session()

    def _compute_backoff_seconds(self, attempt: int, response: Optional[requests.Response] = None) -> float:
        # Prefer server-provided wait hints when available.
        if response is not None:
            retry_after = response.headers.get("Retry-After")
            if retry_after:
                parsed = parse_float(retry_after)
                if parsed is not None and parsed > 0:
                    return min(parsed, self.retry_max_seconds)

            reset_ts = response.headers.get("X-Bapi-Limit-Reset-Timestamp")
            if reset_ts:
                reset_ms = parse_int(reset_ts)
                if reset_ms is not None:
                    now_ms = int(time.time() * 1000)
                    wait_s = (reset_ms - now_ms) / 1000.0
                    if wait_s > 0:
                        return min(wait_s, self.retry_max_seconds)

        exp = self.retry_base_seconds * (2 ** max(0, attempt))
        return min(exp, self.retry_max_seconds)

    def _get(self, path: str, params: dict) -> dict:
        url = f"{self.base_url}{path}"
        last_error: Optional[Exception] = None

        for attempt in range(self.max_retries + 1):
            try:
                resp = self.session.get(url, params=params, timeout=self.timeout_seconds)

                if resp.status_code == 429:
                    if attempt >= self.max_retries:
                        raise RuntimeError("Bybit HTTP 429 Too Many Requests (retry budget exhausted)")
                    wait_s = self._compute_backoff_seconds(attempt, resp)
                    print(
                        f"Rate-limited (HTTP 429) on {path}; retrying in {wait_s:.2f}s "
                        f"[{attempt + 1}/{self.max_retries}]"
                    )
                    time.sleep(wait_s)
                    continue

                resp.raise_for_status()
                payload = resp.json()
                ret_code = int(payload.get("retCode", -1))
                if ret_code == 0:
                    return payload

                # Bybit application-level rate limit.
                if ret_code == 10006:
                    if attempt >= self.max_retries:
                        raise RuntimeError(
                            f"Bybit error retCode=10006 retMsg={payload.get('retMsg')} "
                            f"(retry budget exhausted)"
                        )
                    wait_s = self._compute_backoff_seconds(attempt, resp)
                    print(
                        f"Rate-limited (retCode=10006) on {path}; retrying in {wait_s:.2f}s "
                        f"[{attempt + 1}/{self.max_retries}]"
                    )
                    time.sleep(wait_s)
                    continue

                raise RuntimeError(f"Bybit error retCode={payload.get('retCode')} retMsg={payload.get('retMsg')}")

            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as exc:
                last_error = exc
                if attempt >= self.max_retries:
                    break
                wait_s = self._compute_backoff_seconds(attempt)
                print(
                    f"Transient network error on {path} ({type(exc).__name__}); retrying in {wait_s:.2f}s "
                    f"[{attempt + 1}/{self.max_retries}]"
                )
                time.sleep(wait_s)

            except requests.exceptions.HTTPError as exc:
                last_error = exc
                if attempt >= self.max_retries:
                    break
                wait_s = self._compute_backoff_seconds(attempt)
                print(
                    f"HTTP error on {path} ({exc}); retrying in {wait_s:.2f}s "
                    f"[{attempt + 1}/{self.max_retries}]"
                )
                time.sleep(wait_s)

        if last_error is not None:
            raise RuntimeError(f"Bybit request failed after retries: {last_error}")

        raise RuntimeError("Bybit request failed after retries: unknown error")

    def list_instruments(self, category: str, status: Optional[str] = None) -> List[dict]:
        cursor = None
        out: List[dict] = []
        while True:
            params = {"category": category, "limit": 1000}
            if status:
                params["status"] = status
            if cursor:
                params["cursor"] = cursor
            payload = self._get("/v5/market/instruments-info", params)
            result = payload.get("result") or {}
            items = result.get("list") or []
            out.extend(items)
            cursor = result.get("nextPageCursor") or None
            if not cursor:
                break
        return out

    def fetch_kline(
        self,
        *,
        category: str,
        symbol: str,
        interval: str,
        start_ms: Optional[int],
        end_ms: Optional[int],
        limit: int,
    ) -> List[Candle]:
        params = {
            "category": category,
            "symbol": symbol,
            "interval": interval,
            "limit": limit,
        }
        if start_ms is not None:
            params["start"] = int(start_ms)
        if end_ms is not None:
            params["end"] = int(end_ms)

        payload = self._get("/v5/market/kline", params)
        rows = (payload.get("result") or {}).get("list") or []
        candles = []
        for row in rows:
            if not isinstance(row, list) or len(row) < 7:
                continue
            open_time_ms = parse_int(row[0])
            if open_time_ms is None:
                continue
            c = Candle(
                open_time_ms=open_time_ms,
                open_price=parse_float(row[1], 0.0),
                high_price=parse_float(row[2], 0.0),
                low_price=parse_float(row[3], 0.0),
                close_price=parse_float(row[4], 0.0),
                volume=parse_float(row[5], 0.0),
                turnover=parse_float(row[6], 0.0),
            )
            if c.high_price < max(c.open_price, c.close_price):
                continue
            if c.low_price > min(c.open_price, c.close_price):
                continue
            if c.high_price < c.low_price:
                continue
            candles.append(c)

        candles.sort(key=lambda x: x.open_time_ms)
        return candles


def interval_to_ms(interval: str) -> int:
    if interval == "D":
        return 24 * 60 * 60 * 1000
    if interval == "W":
        return 7 * 24 * 60 * 60 * 1000
    if interval == "M":
        # Not used in this pipeline.
        return 30 * 24 * 60 * 60 * 1000
    return int(interval) * 60 * 1000


def utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def parse_float(value: object, default: Optional[float] = None) -> Optional[float]:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def parse_int(value: object, default: Optional[int] = None) -> Optional[int]:
    try:
        if value is None:
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def load_leverage_buckets(path: Path) -> dict:
    raw = json.loads(path.read_text(encoding="utf-8"))
    out = {
        "major": {"leverage": 5.0, "symbols": set()},
        "large_alt": {"leverage": 3.0, "symbols": set()},
        "mid_cap": {"leverage": 2.0, "symbols": set()},
        "default_leverage": 1.0,
    }
    for bucket in ("major", "large_alt", "mid_cap"):
        item = raw.get(bucket, {}) if isinstance(raw, dict) else {}
        lev = parse_float(item.get("leverage"), out[bucket]["leverage"])
        syms = item.get("symbols") if isinstance(item, dict) else []
        out[bucket]["leverage"] = float(lev or out[bucket]["leverage"])
        out[bucket]["symbols"] = {str(s).upper().strip() for s in syms if str(s).strip()}
    dl = parse_float(raw.get("default_leverage"), 1.0) if isinstance(raw, dict) else 1.0
    out["default_leverage"] = float(dl or 1.0)
    return out


def parse_bucket_selection(raw: str) -> List[str]:
    """Parse comma-separated bucket names.

    Supported bucket names: major, large_alt, mid_cap.
    Returns normalized unique bucket names preserving stable order.
    """
    if not raw or not str(raw).strip():
        return []

    valid = ("major", "large_alt", "mid_cap")
    requested = [x.strip().lower() for x in str(raw).split(",") if x.strip()]
    if not requested:
        return []

    unknown = [x for x in requested if x not in valid]
    if unknown:
        raise ValueError(
            f"Invalid bucket(s): {', '.join(sorted(set(unknown)))}. "
            f"Supported buckets: {', '.join(valid)}"
        )

    out: List[str] = []
    for name in valid:
        if name in requested:
            out.append(name)
    return out


def bucket_base_assets(leverage_buckets: dict, bucket_names: List[str]) -> set:
    """Return base-asset symbols contained in selected leverage buckets."""
    if not bucket_names:
        bucket_names = ["major", "large_alt", "mid_cap"]

    out = set()
    for name in bucket_names:
        out.update(leverage_buckets.get(name, {}).get("symbols", set()))
    return out


def choose_leverage(symbol: str, leverage_buckets: dict) -> Tuple[float, str]:
    base = symbol.split("USDT")[0].replace("/", "").upper()
    if base in leverage_buckets["major"]["symbols"]:
        return float(leverage_buckets["major"]["leverage"]), "major"
    if base in leverage_buckets["large_alt"]["symbols"]:
        return float(leverage_buckets["large_alt"]["leverage"]), "large_alt"
    if base in leverage_buckets["mid_cap"]["symbols"]:
        return float(leverage_buckets["mid_cap"]["leverage"]), "mid_cap"
    return float(leverage_buckets["default_leverage"]), "default"


def calculate_ohlc4(candles: List[Candle]) -> List[float]:
    return [
        (c.open_price + c.high_price + c.low_price + c.close_price) / 4.0
        for c in candles
    ]


def calculate_source_series(candles: List[Candle], source: str) -> List[float]:
    normalized = str(source or "ohlc4").strip().lower()
    if normalized == "open":
        return [c.open_price for c in candles]
    if normalized == "high":
        return [c.high_price for c in candles]
    if normalized == "low":
        return [c.low_price for c in candles]
    if normalized == "close":
        return [c.close_price for c in candles]
    if normalized == "hl2":
        return [(c.high_price + c.low_price) / 2.0 for c in candles]
    if normalized == "hlc3":
        return [(c.high_price + c.low_price + c.close_price) / 3.0 for c in candles]
    if normalized == "ohlc4":
        return calculate_ohlc4(candles)
    raise ValueError(f"Unsupported source: {source}")


def normalize_percent_to_ratio(value: float) -> float:
    # Accept either ratio values (0.025) or percentage values (2.5).
    if abs(value) > 1.0:
        return value / 100.0
    return value


def parse_float_csv(raw: str, field_name: str) -> Tuple[float, ...]:
    items = [x.strip() for x in str(raw).split(",") if x.strip()]
    if not items:
        raise ValueError(f"{field_name} cannot be empty")
    out: List[float] = []
    for item in items:
        try:
            out.append(float(item))
        except ValueError as exc:
            raise ValueError(f"Invalid numeric value in {field_name}: {item}") from exc
    return tuple(out)


def apply_leverage_overrides(leverage_buckets: dict, args: argparse.Namespace) -> None:
    if args.major_leverage is not None:
        leverage_buckets["major"]["leverage"] = float(args.major_leverage)
    if args.large_alt_leverage is not None:
        leverage_buckets["large_alt"]["leverage"] = float(args.large_alt_leverage)
    if args.mid_cap_leverage is not None:
        leverage_buckets["mid_cap"]["leverage"] = float(args.mid_cap_leverage)
    if args.default_leverage is not None:
        leverage_buckets["default_leverage"] = float(args.default_leverage)


def validate_backtest_config(config: BacktestConfig) -> None:
    allowed_sources = {"open", "high", "low", "close", "hl2", "hlc3", "ohlc4"}
    if config.signal_source not in allowed_sources:
        raise ValueError(f"Unsupported signal source: {config.signal_source}")
    if config.btc_regime_source not in allowed_sources:
        raise ValueError(f"Unsupported BTC regime source: {config.btc_regime_source}")

    if config.signal_wma_period <= 0 or config.btc_regime_wma_period <= 0:
        raise ValueError("WMA periods must be positive")
    if config.atr_period <= 0:
        raise ValueError("ATR period must be positive")
    if config.macd_fast_period <= 0 or config.macd_slow_period <= 0 or config.macd_signal_period <= 0:
        raise ValueError("MACD periods must be positive")
    if config.stoch_rsi_period <= 0 or config.stoch_rsi_k_period <= 0 or config.stoch_rsi_d_period <= 0:
        raise ValueError("Stochastic RSI periods must be positive")

    if config.hard_stop_pct < 0:
        raise ValueError("Hard stop percent must be non-negative")
    if config.trailing_trigger_pct < 0 or config.trailing_buffer_pct < 0:
        raise ValueError("Trailing trigger/callback must be non-negative")
    if config.max_hold_minutes <= 0:
        raise ValueError("Time exit must be positive")

    if len(config.partial_levels) != len(config.partial_sizes):
        raise ValueError("partial-levels and partial-sizes must have the same number of elements")
    if any(level <= 0 for level in config.partial_levels):
        raise ValueError("Partial levels must all be > 0")
    if any(size <= 0 for size in config.partial_sizes):
        raise ValueError("Partial sizes must all be > 0")
    if sum(config.partial_sizes) > 1.0 + 1e-9:
        raise ValueError("Sum of partial sizes cannot exceed 1.0 (100%)")


def collect_provided_cli_flags(argv_tokens: List[str]) -> set:
    out = set()
    for token in argv_tokens:
        if not token.startswith("--"):
            continue
        flag = token.split("=", 1)[0]
        out.add(flag)
    return out


def apply_run_recipe(args: argparse.Namespace) -> None:
    if getattr(args, "command", None) != "run":
        return

    recipe = str(getattr(args, "recipe", "") or "").strip().lower()
    if not recipe:
        return
    if recipe != "baseline":
        raise ValueError(f"Unsupported recipe: {recipe}")

    provided_flags = set(getattr(args, "_provided_flags", set()))

    baseline_values = {
        "signal_source": ("ohlc4", "--signal-source"),
        "signal_wma_period": (45, "--signal-wma-period"),
        "signal_wma_offset": (2, "--signal-wma-offset"),
        "btc_regime_source": ("ohlc4", "--btc-regime-source"),
        "btc_regime_wma_period": (90, "--btc-regime-wma-period"),
        "btc_regime_wma_offset": (0, "--btc-regime-wma-offset"),
        "hard_stop_pct": (2.5, "--hard-stop-pct"),
        "partial_levels": ("2,3,5", "--partial-levels"),
        "partial_sizes": ("25,25,25", "--partial-sizes"),
        "trailing_activation_pct": (2.0, "--trailing-activation-pct"),
        "trailing_callback_pct": (1.5, "--trailing-callback-pct"),
        "time_exit_hours": (40.0, "--time-exit-hours"),
        "atr_period": (14, "--atr-period"),
        "atr_volatility_cutoff_pct": (5.0, "--atr-volatility-cutoff-pct"),
        "atr_size_scalar": (0.5, "--atr-size-scalar"),
        "macd_fast": (2, "--macd-fast"),
        "macd_slow": (39, "--macd-slow"),
        "macd_signal": (6, "--macd-signal"),
        "stoch_rsi_period": (14, "--stoch-rsi-period"),
        "stoch_rsi_k": (3, "--stoch-rsi-k"),
        "stoch_rsi_d": (3, "--stoch-rsi-d"),
    }

    for field_name, (baseline_value, controlling_flag) in baseline_values.items():
        if controlling_flag in provided_flags:
            continue
        setattr(args, field_name, baseline_value)


def calculate_wma_at(source_prices: List[float], idx: int, period: int = 45, offset: int = 2) -> Optional[float]:
    if idx < 0:
        return None
    available = source_prices[: idx + 1]
    if len(available) < period + offset:
        return None
    slice_prices = available[: -(offset) if offset > 0 else None]
    if len(slice_prices) < period:
        return None
    weights = list(range(1, period + 1))
    values = slice_prices[-period:]
    num = sum(v * w for v, w in zip(values, weights))
    den = sum(weights)
    return num / den


def calculate_wma_series(source_prices: List[float], period: int, offset: int) -> List[Optional[float]]:
    return [calculate_wma_at(source_prices, i, period=period, offset=offset) for i in range(len(source_prices))]


def calculate_atr(candles: List[Candle], idx: int, period: int = 14) -> Optional[float]:
    if idx < period:
        return None
    trs = []
    start = max(1, idx - period + 1)
    for i in range(start, idx + 1):
        cur = candles[i]
        prev_close = candles[i - 1].close_price
        tr = max(
            cur.high_price - cur.low_price,
            abs(cur.high_price - prev_close),
            abs(cur.low_price - prev_close),
        )
        trs.append(tr)
    if len(trs) < period:
        return None
    return sum(trs[-period:]) / period


def calculate_ema_series(values: List[float], period: int) -> List[Optional[float]]:
    if period <= 0:
        raise ValueError("EMA period must be positive")

    out: List[Optional[float]] = [None] * len(values)
    if len(values) < period:
        return out

    multiplier = 2.0 / (period + 1)
    ema = sum(values[:period]) / period
    out[period - 1] = ema

    for idx in range(period, len(values)):
        ema = ((values[idx] - ema) * multiplier) + ema
        out[idx] = ema

    return out


def calculate_macd_diff_series(
    values: List[float],
    fast_period: int = 2,
    slow_period: int = 39,
    signal_period: int = 6,
) -> List[Optional[float]]:
    fast_ema = calculate_ema_series(values, fast_period)
    slow_ema = calculate_ema_series(values, slow_period)

    macd_line: List[Optional[float]] = [None] * len(values)
    macd_values: List[float] = []
    macd_indexes: List[int] = []
    for idx in range(len(values)):
        fast = fast_ema[idx]
        slow = slow_ema[idx]
        if fast is None or slow is None:
            continue
        value = fast - slow
        macd_line[idx] = value
        macd_values.append(value)
        macd_indexes.append(idx)

    signal_partial = calculate_ema_series(macd_values, signal_period)
    out: List[Optional[float]] = [None] * len(values)
    for series_idx, candle_idx in enumerate(macd_indexes):
        signal = signal_partial[series_idx]
        macd = macd_line[candle_idx]
        if signal is None or macd is None:
            continue
        out[candle_idx] = macd - signal
    return out


def calculate_rsi_series(values: List[float], period: int = 14) -> List[Optional[float]]:
    out: List[Optional[float]] = [None] * len(values)
    if period <= 0 or len(values) <= period:
        return out

    gains: List[float] = []
    losses: List[float] = []
    for idx in range(1, period + 1):
        change = values[idx] - values[idx - 1]
        gains.append(max(change, 0.0))
        losses.append(max(-change, 0.0))

    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period

    if avg_loss == 0:
        out[period] = 100.0
    else:
        rs = avg_gain / avg_loss
        out[period] = 100.0 - (100.0 / (1.0 + rs))

    for idx in range(period + 1, len(values)):
        change = values[idx] - values[idx - 1]
        gain = max(change, 0.0)
        loss = max(-change, 0.0)
        avg_gain = ((avg_gain * (period - 1)) + gain) / period
        avg_loss = ((avg_loss * (period - 1)) + loss) / period

        if avg_loss == 0:
            out[idx] = 100.0
        else:
            rs = avg_gain / avg_loss
            out[idx] = 100.0 - (100.0 / (1.0 + rs))

    return out


def calculate_sma_optional_series(values: List[Optional[float]], period: int) -> List[Optional[float]]:
    out: List[Optional[float]] = [None] * len(values)
    if period <= 0:
        raise ValueError("SMA period must be positive")

    window: List[float] = []
    for idx, value in enumerate(values):
        if value is None:
            window = []
            continue
        window.append(value)
        if len(window) > period:
            window.pop(0)
        if len(window) == period:
            out[idx] = sum(window) / period
    return out


def calculate_stoch_rsi_series(
    values: List[float],
    rsi_period: int = 14,
    k_period: int = 3,
    d_period: int = 3,
) -> Tuple[List[Optional[float]], List[Optional[float]]]:
    rsi_series = calculate_rsi_series(values, period=rsi_period)
    stoch_raw: List[Optional[float]] = [None] * len(values)

    for idx in range(len(values)):
        if idx < rsi_period:
            continue
        window = rsi_series[idx - rsi_period + 1 : idx + 1]
        if len(window) < rsi_period or any(value is None for value in window):
            continue
        typed_window = [float(value) for value in window if value is not None]
        lowest = min(typed_window)
        highest = max(typed_window)
        current = rsi_series[idx]
        if current is None:
            continue
        if math.isclose(highest, lowest):
            stoch_raw[idx] = 0.0
        else:
            stoch_raw[idx] = ((current - lowest) / (highest - lowest)) * 100.0

    k_series = calculate_sma_optional_series(stoch_raw, k_period)
    d_series = calculate_sma_optional_series(k_series, d_period)
    return k_series, d_series


def confirm_signal(
    candles: List[Candle],
    ohlc4_values: List[float],
    wma_values: List[Optional[float]],
    current_index: int,
    signal_type: str,
) -> bool:
    if signal_type not in {"BUY", "SELL"}:
        return False
    prior = current_index - 1
    if prior < 0:
        return False

    consec: List[int] = []
    for i in range(prior, -1, -1):
        w = wma_values[i]
        if w is None:
            break
        diff = ohlc4_values[i] - w
        positive = diff > 0
        if signal_type == "BUY" and positive:
            consec.append(i)
        elif signal_type == "SELL" and not positive:
            consec.append(i)
        else:
            break

    if len(consec) < 1:
        return False

    if signal_type == "BUY":
        hh = max(consec, key=lambda x: candles[x].high_price)
        return candles[prior].close_price > candles[hh].close_price

    ll = min(consec, key=lambda x: candles[x].low_price)
    return candles[prior].close_price < candles[ll].close_price


def derive_pnl_pct(entry_price: float, current_price: float, side: str) -> float:
    if entry_price <= 0:
        return 0.0
    if side == "long":
        return ((current_price - entry_price) / entry_price) * 100.0
    return ((entry_price - current_price) / entry_price) * 100.0


def net_pnl(entry_price: float, exit_price: float, qty: float, side: str, round_trip_fee_rate: float) -> float:
    if side == "long":
        gross = (exit_price - entry_price) * qty
    else:
        gross = (entry_price - exit_price) * qty
    avg_notional = ((entry_price + exit_price) / 2.0) * qty
    fee_cost = avg_notional * round_trip_fee_rate
    return gross - fee_cost


def instrument_effective_start(item: dict, override_start_ms: Optional[int]) -> Optional[int]:
    launch = parse_int(item.get("launchTime"))
    if launch is None:
        return override_start_ms
    if override_start_ms is None:
        return launch
    return max(launch, override_start_ms)


def instrument_effective_end(item: dict, override_end_ms: Optional[int]) -> int:
    now_ms = int(time.time() * 1000)
    delivery = parse_int(item.get("deliveryTime"), 0)
    end_candidate = now_ms
    if delivery and delivery > 0:
        end_candidate = min(end_candidate, delivery)
    if override_end_ms is not None:
        end_candidate = min(end_candidate, override_end_ms)
    return end_candidate


def fetch_and_store_full_history(args: argparse.Namespace) -> None:
    db_path = Path(args.db)
    store = SQLiteStore(db_path)
    base_url = BYBIT_TESTNET if args.testnet else BYBIT_MAINNET
    client = BybitPublicClient(
        base_url=base_url,
        timeout_seconds=args.timeout_seconds,
        max_retries=args.max_retries,
        retry_base_seconds=args.retry_base_seconds,
        retry_max_seconds=args.retry_max_seconds,
    )

    category = args.category
    interval = args.interval
    limit = max(1, min(1000, int(args.limit)))
    sleep_seconds = max(0.0, float(args.sleep_seconds))

    run_id = f"ingest-{utc_now().strftime('%Y%m%dT%H%M%SZ')}"
    started_at = utc_now().isoformat()

    all_items = client.list_instruments(category=category)
    snapshot_id = f"snapshot-{utc_now().strftime('%Y%m%dT%H%M%SZ')}"
    for item in all_items:
        store.insert_instrument_snapshot(snapshot_id, started_at, category, item)
    store.conn.commit()

    leverage_buckets = load_leverage_buckets(Path(args.leverage_config))
    selected_buckets = parse_bucket_selection(args.buckets)
    preferred_base_assets = bucket_base_assets(leverage_buckets, selected_buckets)

    symbol_filter = set()
    if args.symbols:
        symbol_filter = {s.strip().upper() for s in args.symbols.split(",") if s.strip()}

    selected: List[dict] = []
    for item in all_items:
        symbol = str(item.get("symbol") or "").upper()
        status = str(item.get("status") or "")
        base_coin = str(item.get("baseCoin") or "").upper()
        quote_coin = str(item.get("quoteCoin") or "").upper()
        contract_type = str(item.get("contractType") or "")

        if quote_coin != "USDT":
            continue
        if "Perpetual" not in contract_type:
            continue
        if args.only_trading and status != "Trading":
            continue

        if symbol_filter:
            if symbol not in symbol_filter:
                continue
        else:
            if not args.include_all_linear and base_coin not in preferred_base_assets and symbol != "BTCUSDT":
                continue

        selected.append(item)

    selected.sort(key=lambda x: str(x.get("symbol") or ""))
    symbols = [str(i.get("symbol") or "").upper() for i in selected]

    store.record_ingestion_run_start(
        run_id,
        started_at,
        base_url,
        category,
        interval,
        len(symbols),
        {
            "snapshot_id": snapshot_id,
            "selected_symbols": symbols,
            "selected_buckets": selected_buckets,
            "include_all_linear": bool(args.include_all_linear),
            "only_trading": bool(args.only_trading),
        },
    )

    total_requests = 0
    total_candles = 0

    for idx, item in enumerate(selected, start=1):
        symbol = str(item.get("symbol") or "").upper()
        start_ms = instrument_effective_start(item, args.start_ms)
        end_ms = instrument_effective_end(item, args.end_ms)

        if start_ms is None or start_ms >= end_ms:
            print(f"[{idx}/{len(selected)}] {symbol}: skipped (invalid time window)")
            continue

        current_end = end_ms
        symbol_candles = 0
        symbol_requests = 0

        while True:
            page = client.fetch_kline(
                category=category,
                symbol=symbol,
                interval=interval,
                start_ms=start_ms,
                end_ms=current_end,
                limit=limit,
            )
            total_requests += 1
            symbol_requests += 1

            if not page:
                break

            ingested_at = utc_now().isoformat()
            min_open = None
            for candle in page:
                store.upsert_candle(
                    category=category,
                    symbol=symbol,
                    interval=interval,
                    candle=candle,
                    run_id=run_id,
                    ingested_at_utc=ingested_at,
                )
                symbol_candles += 1
                total_candles += 1
                if min_open is None or candle.open_time_ms < min_open:
                    min_open = candle.open_time_ms

            store.conn.commit()
            store.record_ingestion_run_progress(run_id, total_requests, total_candles)

            if min_open is None:
                break
            if min_open <= start_ms:
                break

            next_end = min_open - 1
            if next_end >= current_end:
                break
            current_end = next_end

            if args.max_pages and symbol_requests >= args.max_pages:
                break

            if sleep_seconds > 0:
                time.sleep(sleep_seconds)

        print(
            f"[{idx}/{len(selected)}] {symbol}: requests={symbol_requests}, candles_upserted={symbol_candles}, "
            f"window=[{start_ms}, {end_ms}]"
        )

    finished_at = utc_now().isoformat()
    store.record_ingestion_run_end(run_id, finished_at)

    manifest = store.create_manifest(
        run_id=run_id,
        category=category,
        interval=interval,
        start_ms=args.start_ms,
        end_ms=args.end_ms,
        symbols=symbols,
        notes={
            "label": args.manifest_label,
            "selected_buckets": selected_buckets,
            "started_at": started_at,
            "finished_at": finished_at,
            "base_url": base_url,
            "request_count": total_requests,
            "candle_upserts": total_candles,
        },
    )

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{manifest['manifest_id']}.json"
    out_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print("Backfill complete")
    print(f"  run_id: {run_id}")
    print(f"  symbols: {len(symbols)}")
    print(f"  requests: {total_requests}")
    print(f"  candle_upserts: {total_candles}")
    print(f"  manifest: {out_path}")

    store.close()


class BacktestRunner:
    def __init__(
        self,
        *,
        store: SQLiteStore,
        category: str,
        interval: str,
        symbols: List[str],
        btc_symbol: str,
        start_ms: Optional[int],
        end_ms: Optional[int],
        leverage_buckets: dict,
        config: BacktestConfig,
    ) -> None:
        self.store = store
        self.category = category
        self.interval = interval
        self.symbols = symbols
        self.btc_symbol = btc_symbol
        self.start_ms = start_ms
        self.end_ms = end_ms
        self.leverage_buckets = leverage_buckets
        self.config = config

        self.candle_map: Dict[str, List[Candle]] = {}
        self.time_to_index: Dict[str, Dict[int, int]] = {}
        self.ohlc4_map: Dict[str, List[float]] = {}
        self.wma45_map: Dict[str, List[Optional[float]]] = {}
        self.atr14_map: Dict[str, List[Optional[float]]] = {}
        self.macd_diff_map: Dict[str, List[Optional[float]]] = {}
        self.stoch_rsi_k_map: Dict[str, List[Optional[float]]] = {}
        self.stoch_rsi_d_map: Dict[str, List[Optional[float]]] = {}
        self.btc_regime_by_time: Dict[int, str] = {}

        self.balance = config.initial_balance
        self.initial_balance = config.initial_balance
        self.total_pnl = 0.0
        self.total_trades = 0
        self.winning_trades = 0
        self.losing_trades = 0
        self.closed_trades: List[dict] = []
        self.equity_curve: List[dict] = []
        self.positions: Dict[str, Position] = {}

        self.current_day: Optional[dt.date] = None
        self.session_start_balance = config.initial_balance
        self.daily_drawdown_paused = False
        self.consecutive_losses = 0
        self.cooldown_until_ms: Optional[int] = None

    def load(self) -> None:
        all_symbols = sorted(set(self.symbols + [self.btc_symbol]))
        for symbol in all_symbols:
            candles = self.store.fetch_candles(
                category=self.category,
                symbol=symbol,
                interval=self.interval,
                start_ms=self.start_ms,
                end_ms=self.end_ms,
            )
            if candles:
                self.candle_map[symbol] = candles
                self.time_to_index[symbol] = {c.open_time_ms: i for i, c in enumerate(candles)}
                source_series = calculate_source_series(candles, self.config.signal_source)
                self.ohlc4_map[symbol] = source_series
                self.wma45_map[symbol] = calculate_wma_series(
                    source_series,
                    period=self.config.signal_wma_period,
                    offset=self.config.signal_wma_offset,
                )
                self.atr14_map[symbol] = [calculate_atr(candles, i, period=self.config.atr_period) for i in range(len(candles))]
                self.macd_diff_map[symbol] = calculate_macd_diff_series(
                    source_series,
                    fast_period=self.config.macd_fast_period,
                    slow_period=self.config.macd_slow_period,
                    signal_period=self.config.macd_signal_period,
                )
                stoch_k, stoch_d = calculate_stoch_rsi_series(
                    source_series,
                    rsi_period=self.config.stoch_rsi_period,
                    k_period=self.config.stoch_rsi_k_period,
                    d_period=self.config.stoch_rsi_d_period,
                )
                self.stoch_rsi_k_map[symbol] = stoch_k
                self.stoch_rsi_d_map[symbol] = stoch_d

        if self.btc_symbol not in self.candle_map:
            raise RuntimeError(f"Missing BTC regime candles for {self.btc_symbol}")

        btc_candles = self.candle_map[self.btc_symbol]
        btc_series = calculate_source_series(btc_candles, self.config.btc_regime_source)
        btc_wma90 = calculate_wma_series(
            btc_series,
            period=self.config.btc_regime_wma_period,
            offset=self.config.btc_regime_wma_offset,
        )
        for idx, candle in enumerate(btc_candles):
            wma = btc_wma90[idx]
            if wma is None:
                continue
            self.btc_regime_by_time[candle.open_time_ms] = "BUY" if btc_series[idx] > wma else "SELL"

    def _update_daily_session(self, ts_ms: int) -> None:
        day = dt.datetime.fromtimestamp(ts_ms / 1000, tz=dt.timezone.utc).date()
        if self.current_day is None or day != self.current_day:
            self.current_day = day
            self.session_start_balance = self.balance
            self.daily_drawdown_paused = False

        if self.session_start_balance > 0:
            drawdown = (self.balance - self.session_start_balance) / self.session_start_balance
            if drawdown <= self.config.daily_drawdown_limit:
                self.daily_drawdown_paused = True

    def _in_cooldown(self, ts_ms: int) -> bool:
        if self.cooldown_until_ms is None:
            return False
        return ts_ms < self.cooldown_until_ms

    def _entry_blocked(self, ts_ms: int) -> bool:
        return self.daily_drawdown_paused or self._in_cooldown(ts_ms)

    def _regime_signal(self, ts_ms: int) -> Optional[str]:
        return self.btc_regime_by_time.get(ts_ms)

    def _symbol_signal(self, symbol: str, ts_ms: int) -> Optional[dict]:
        candles = self.candle_map.get(symbol)
        if not candles:
            return None
        idx_map = self.time_to_index.get(symbol)
        if idx_map is None:
            return None
        idx = idx_map.get(ts_ms)
        if idx is None:
            return None
        min_wma_index = self.config.signal_wma_period + max(0, self.config.signal_wma_offset) - 1
        if idx < min_wma_index:
            return None

        ohlc4 = self.ohlc4_map.get(symbol)
        wma_series = self.wma45_map.get(symbol)
        atr_series = self.atr14_map.get(symbol)
        macd_diff_series = self.macd_diff_map.get(symbol)
        stoch_k_series = self.stoch_rsi_k_map.get(symbol)
        stoch_d_series = self.stoch_rsi_d_map.get(symbol)
        if (
            ohlc4 is None
            or wma_series is None
            or atr_series is None
            or macd_diff_series is None
            or stoch_k_series is None
            or stoch_d_series is None
        ):
            return None

        w = wma_series[idx]
        if w is None:
            return None

        current = ohlc4[idx]
        atr = atr_series[idx]
        atr_ratio = (atr / current) if (atr is not None and current > 0) else 0.0
        signal_type = "BUY" if (current - w) > 0 else "SELL"
        confirmed = confirm_signal(candles, ohlc4, wma_series, idx, signal_type)
        indicator_confirmed = self._confirm_optional_indicators(
            signal_type=signal_type,
            signal_index=idx,
            macd_diff_series=macd_diff_series,
            stoch_k_series=stoch_k_series,
            stoch_d_series=stoch_d_series,
        )

        return {
            "symbol": symbol,
            "signal": signal_type,
            "confirmed": bool(confirmed and indicator_confirmed),
            "current_price": current,
            "atr_ratio": atr_ratio,
            "index": idx,
        }

    def _confirm_optional_indicators(
        self,
        *,
        signal_type: str,
        signal_index: int,
        macd_diff_series: List[Optional[float]],
        stoch_k_series: List[Optional[float]],
        stoch_d_series: List[Optional[float]],
    ) -> bool:
        check_index = signal_index - 1
        if check_index < 0:
            return False

        if self.config.require_macd_confirmation:
            macd_diff = macd_diff_series[check_index]
            if macd_diff is None:
                return False
            if signal_type == "BUY" and macd_diff <= 0:
                return False
            if signal_type == "SELL" and macd_diff >= 0:
                return False

        if self.config.require_stoch_rsi_confirmation:
            stoch_k = stoch_k_series[check_index]
            stoch_d = stoch_d_series[check_index]
            if stoch_k is None or stoch_d is None:
                return False
            if signal_type == "BUY" and stoch_k <= stoch_d:
                return False
            if signal_type == "SELL" and stoch_k >= stoch_d:
                return False
            # Prevent BUY signals when Stoch RSI is in overbought zone (> 80)
            if signal_type == "BUY" and stoch_k > 80:
                return False
            # Prevent SELL signals when Stoch RSI is in oversold zone (< 20)
            if signal_type == "SELL" and stoch_k < 20:
                return False

        return True

    def _open_position(self, symbol: str, signal: str, fill_price: float, ts_ms: int, atr_ratio: float) -> bool:
        if symbol in self.positions:
            return False
        if len(self.positions) >= self.config.max_open_positions:
            return False
        if fill_price <= 0:
            return False

        risk_pct = self.config.entry_risk_pct
        if atr_ratio > self.config.atr_volatility_cutoff:
            risk_pct *= self.config.atr_size_scalar

        leverage, tier = choose_leverage(symbol, self.leverage_buckets)
        gross_notional = self.balance * risk_pct * leverage
        net_notional = gross_notional * (1 - self.config.round_trip_fee_rate)
        qty = net_notional / fill_price
        if qty <= 0:
            return False

        side = "long" if signal == "BUY" else "short"
        pos = Position(
            symbol=symbol,
            side=side,
            entry_price=fill_price,
            quantity=qty,
            entry_time_ms=ts_ms,
            leverage=leverage,
            leverage_tier=tier,
            round_trip_fee_rate=self.config.round_trip_fee_rate,
        )
        self.positions[symbol] = pos
        self.total_trades += 1
        return True

    def _close_position(self, pos: Position, exit_price: float, ts_ms: int, reason: str) -> None:
        pnl = net_pnl(pos.entry_price, exit_price, pos.quantity, pos.side, pos.round_trip_fee_rate)
        pnl_pct = derive_pnl_pct(pos.entry_price, exit_price, pos.side)
        self.balance += pnl
        self.total_pnl += pnl
        if pnl > 0:
            self.winning_trades += 1
            self.consecutive_losses = 0
        else:
            self.losing_trades += 1
            self.consecutive_losses += 1
            if self.consecutive_losses >= self.config.max_consecutive_losses:
                self.cooldown_until_ms = ts_ms + (self.config.cooldown_candles * MS_PER_4H)

        self.closed_trades.append(
            {
                "symbol": pos.symbol,
                "side": pos.side,
                "entry_time_ms": pos.entry_time_ms,
                "exit_time_ms": ts_ms,
                "entry_price": pos.entry_price,
                "exit_price": exit_price,
                "quantity": pos.quantity,
                "pnl": pnl,
                "pnl_pct": pnl_pct,
                "reason": reason,
                "partials": list(pos.partial_exits),
                "leverage": pos.leverage,
                "leverage_tier": pos.leverage_tier,
            }
        )
        self.positions.pop(pos.symbol, None)

    def _apply_partial(self, pos: Position, level: float, size: float, fill_price: float, ts_ms: int) -> None:
        close_qty = pos.quantity * size
        if close_qty <= 0:
            return
        partial_pnl = net_pnl(pos.entry_price, fill_price, close_qty, pos.side, pos.round_trip_fee_rate)
        pos.quantity = max(0.0, pos.quantity - close_qty)
        self.balance += partial_pnl
        self.total_pnl += partial_pnl
        pos.partial_exits.append(
            {
                "time_ms": ts_ms,
                "level": level,
                "size": size,
                "qty": close_qty,
                "pnl": partial_pnl,
                "fill_price": fill_price,
            }
        )

    def _update_position_intrabar(self, pos: Position, candle: Candle, ts_ms: int) -> None:
        stop_price = pos.entry_price * (1 - self.config.hard_stop_pct) if pos.side == "long" else pos.entry_price * (1 + self.config.hard_stop_pct)
        time_elapsed_minutes = (ts_ms - pos.entry_time_ms) / 60000.0

        if pos.side == "long":
            adverse = candle.low_price
            favorable = candle.high_price
            close_px = candle.close_price
            partial_prices = [pos.entry_price * (1 + lv) for lv in self.config.partial_levels]
        else:
            adverse = candle.high_price
            favorable = candle.low_price
            close_px = candle.close_price
            partial_prices = [pos.entry_price * (1 - lv) for lv in self.config.partial_levels]

        if (pos.side == "long" and adverse <= stop_price) or (pos.side == "short" and adverse >= stop_price):
            self._close_position(pos, stop_price, ts_ms, "stop_loss")
            return

        if pos.trailing_stop_active and pos.trailing_stop_level is not None:
            if (pos.side == "long" and adverse <= pos.trailing_stop_level) or (pos.side == "short" and adverse >= pos.trailing_stop_level):
                self._close_position(pos, pos.trailing_stop_level, ts_ms, "TRAILING_STOP")
                return

        for i, level in enumerate(self.config.partial_levels):
            already = any(abs(float(x.get("level", -1)) - level) < 1e-12 for x in pos.partial_exits)
            if already:
                continue
            target = partial_prices[i]
            hit = (pos.side == "long" and favorable >= target) or (pos.side == "short" and favorable <= target)
            if hit:
                self._apply_partial(pos, level, self.config.partial_sizes[i], target, ts_ms)
                if pos.quantity <= 0:
                    self.positions.pop(pos.symbol, None)
                    return

        pnl_pct_favorable = derive_pnl_pct(pos.entry_price, favorable, pos.side)
        if pnl_pct_favorable > pos.peak_pnl_pct:
            pos.peak_pnl_pct = pnl_pct_favorable

        if (not pos.trailing_stop_active) and pnl_pct_favorable >= (self.config.trailing_trigger_pct * 100.0):
            pos.trailing_stop_active = True

        if pos.trailing_stop_active:
            if pos.side == "long":
                peak_price = pos.entry_price * (1 + (pos.peak_pnl_pct / 100.0))
                candidate = peak_price * (1 - self.config.trailing_buffer_pct)
                if pos.trailing_stop_level is None or candidate > pos.trailing_stop_level:
                    pos.trailing_stop_level = candidate
            else:
                trough_price = pos.entry_price * (1 - (pos.peak_pnl_pct / 100.0))
                candidate = trough_price * (1 + self.config.trailing_buffer_pct)
                if pos.trailing_stop_level is None or candidate < pos.trailing_stop_level:
                    pos.trailing_stop_level = candidate

            if pos.trailing_stop_level is not None:
                if (pos.side == "long" and close_px <= pos.trailing_stop_level) or (pos.side == "short" and close_px >= pos.trailing_stop_level):
                    self._close_position(pos, pos.trailing_stop_level, ts_ms, "TRAILING_STOP")
                    return

        if time_elapsed_minutes >= self.config.max_hold_minutes:
            self._close_position(pos, close_px, ts_ms, "time_exit")

    def run(self) -> dict:
        self.load()

        timeline = [c.open_time_ms for c in self.candle_map[self.btc_symbol]]
        warmup_required = max(
            self.config.signal_wma_period + max(0, self.config.signal_wma_offset) - 1,
            self.config.btc_regime_wma_period + max(0, self.config.btc_regime_wma_offset) - 1,
            self.config.atr_period,
            self.config.macd_slow_period + self.config.macd_signal_period - 2,
            self.config.stoch_rsi_period + self.config.stoch_rsi_k_period + self.config.stoch_rsi_d_period - 2,
        )
        if len(timeline) < warmup_required + 2:
            raise RuntimeError("Insufficient BTC candles for regime and warmup")

        total_steps = len(timeline)
        progress_stride = max(1, total_steps // 20)  # ~5% checkpoints.
        run_start = time.time()
        start_ts_ms = timeline[0]
        end_ts_ms = timeline[-1]
        print(
            "Backtest run started: "
            f"symbols={len(self.symbols)}, candles={total_steps}, "
            f"window=[{start_ts_ms}, {end_ts_ms}]"
        )

        pending_entries: List[dict] = []

        for t_idx, ts_ms in enumerate(timeline):
            self._update_daily_session(ts_ms)

            executable = [x for x in pending_entries if x["execute_at_ms"] == ts_ms]
            for req in executable:
                symbol = req["symbol"]
                candles = self.candle_map.get(symbol)
                if not candles:
                    continue
                idx = self.time_to_index[symbol].get(ts_ms)
                if idx is None:
                    continue
                open_price = candles[idx].open_price
                self._open_position(symbol, req["signal"], open_price, ts_ms, req["atr_ratio"])

            pending_entries = [x for x in pending_entries if x["execute_at_ms"] != ts_ms]

            for symbol in list(self.positions.keys()):
                pos = self.positions.get(symbol)
                if pos is None:
                    continue
                candles = self.candle_map.get(symbol)
                if not candles:
                    continue
                idx = self.time_to_index[symbol].get(ts_ms)
                if idx is None:
                    continue
                self._update_position_intrabar(pos, candles[idx], ts_ms)

            regime = self._regime_signal(ts_ms)
            if regime is None:
                self._record_equity(ts_ms)
                continue

            if self._entry_blocked(ts_ms):
                self._record_equity(ts_ms)
                continue

            for symbol in self.symbols:
                if symbol in self.positions:
                    continue
                if any(e["symbol"] == symbol for e in pending_entries):
                    continue

                s = self._symbol_signal(symbol, ts_ms)
                if not s or not s["confirmed"]:
                    continue
                if s["signal"] != regime:
                    continue

                execute_at_ms = ts_ms + interval_to_ms(self.interval)
                if execute_at_ms not in self.time_to_index.get(symbol, {}):
                    continue

                pending_entries.append(
                    {
                        "symbol": symbol,
                        "signal": s["signal"],
                        "atr_ratio": s["atr_ratio"],
                        "created_at_ms": ts_ms,
                        "execute_at_ms": execute_at_ms,
                    }
                )

            self._record_equity(ts_ms)

            step = t_idx + 1
            if step == 1 or step % progress_stride == 0 or step == total_steps:
                elapsed = max(0.0, time.time() - run_start)
                pct = (step / total_steps) * 100.0 if total_steps > 0 else 100.0
                eta_seconds = ((elapsed / step) * (total_steps - step)) if step > 0 else 0.0
                print(
                    "Run progress: "
                    f"{step}/{total_steps} ({pct:.1f}%), "
                    f"open_positions={len(self.positions)}, "
                    f"closed_trades={len(self.closed_trades)}, "
                    f"elapsed={elapsed:.1f}s, eta={eta_seconds:.1f}s"
                )

        final_ts = timeline[-1]
        for symbol in list(self.positions.keys()):
            pos = self.positions[symbol]
            idx = self.time_to_index[symbol].get(final_ts)
            if idx is None:
                continue
            close_px = self.candle_map[symbol][idx].close_price
            self._close_position(pos, close_px, final_ts, "end_of_test")

        self._record_equity(final_ts)

        summary = self._build_summary()
        return summary

    def _record_equity(self, ts_ms: int) -> None:
        unrealized = 0.0
        for symbol, pos in self.positions.items():
            idx = self.time_to_index[symbol].get(ts_ms)
            if idx is None:
                continue
            close_px = self.candle_map[symbol][idx].close_price
            unrealized += net_pnl(pos.entry_price, close_px, pos.quantity, pos.side, pos.round_trip_fee_rate)
        equity = self.balance + unrealized
        self.equity_curve.append(
            {
                "time_ms": ts_ms,
                "balance": self.balance,
                "unrealized_pnl": unrealized,
                "equity": equity,
            }
        )

    def _build_summary(self) -> dict:
        max_equity = -float("inf")
        max_drawdown = 0.0
        for row in self.equity_curve:
            eq = row["equity"]
            if eq > max_equity:
                max_equity = eq
            if max_equity > 0:
                dd = (eq - max_equity) / max_equity
                if dd < max_drawdown:
                    max_drawdown = dd

        total_return = (self.balance - self.initial_balance) / self.initial_balance if self.initial_balance > 0 else 0.0
        win_rate = (self.winning_trades / len(self.closed_trades)) if self.closed_trades else 0.0

        reason_counts: Dict[str, int] = {}
        for t in self.closed_trades:
            r = str(t.get("reason") or "unknown")
            reason_counts[r] = reason_counts.get(r, 0) + 1

        return {
            "initial_balance": self.initial_balance,
            "final_balance": self.balance,
            "total_pnl": self.total_pnl,
            "total_return": total_return,
            "closed_trades": len(self.closed_trades),
            "win_rate": win_rate,
            "winning_trades": self.winning_trades,
            "losing_trades": self.losing_trades,
            "max_drawdown": max_drawdown,
            "reason_counts": reason_counts,
        }


def write_backtest_artifacts(
    *,
    out_dir: Path,
    summary: dict,
    trades: List[dict],
    equity_curve: List[dict],
    metadata: dict,
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)

    summary_path = out_dir / "summary.json"
    summary_payload = {**summary, "metadata": metadata}
    summary_path.write_text(json.dumps(summary_payload, indent=2), encoding="utf-8")

    trades_path = out_dir / "trades.csv"
    with trades_path.open("w", newline="", encoding="utf-8") as f:
        fieldnames = [
            "symbol",
            "side",
            "entry_time_ms",
            "exit_time_ms",
            "entry_price",
            "exit_price",
            "quantity",
            "pnl",
            "pnl_pct",
            "reason",
            "leverage",
            "leverage_tier",
            "partials_json",
        ]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in trades:
            writer.writerow(
                {
                    "symbol": row.get("symbol"),
                    "side": row.get("side"),
                    "entry_time_ms": row.get("entry_time_ms"),
                    "exit_time_ms": row.get("exit_time_ms"),
                    "entry_price": row.get("entry_price"),
                    "exit_price": row.get("exit_price"),
                    "quantity": row.get("quantity"),
                    "pnl": row.get("pnl"),
                    "pnl_pct": row.get("pnl_pct"),
                    "reason": row.get("reason"),
                    "leverage": row.get("leverage"),
                    "leverage_tier": row.get("leverage_tier"),
                    "partials_json": json.dumps(row.get("partials") or [], separators=(",", ":"), sort_keys=True),
                }
            )

    equity_path = out_dir / "equity_curve.csv"
    with equity_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["time_ms", "balance", "unrealized_pnl", "equity"])
        writer.writeheader()
        writer.writerows(equity_curve)

    manifest_path = out_dir / "run_manifest.json"
    run_hash = hashlib.sha256(
        json.dumps(
            {
                "summary": summary,
                "metadata": metadata,
                "trade_count": len(trades),
                "equity_points": len(equity_curve),
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    manifest_path.write_text(
        json.dumps(
            {
                "created_at_utc": utc_now().isoformat(),
                "run_sha256": run_hash,
                "summary_path": str(summary_path),
                "trades_path": str(trades_path),
                "equity_curve_path": str(equity_path),
                "metadata": metadata,
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def run_backtest(args: argparse.Namespace) -> None:
    store = SQLiteStore(Path(args.db))
    available_symbols = store.list_symbols_with_candles(args.category, args.interval)
    if not available_symbols:
        raise RuntimeError("No candles found in DB. Run backfill first.")

    leverage_buckets = load_leverage_buckets(Path(args.leverage_config))
    apply_leverage_overrides(leverage_buckets, args)
    selected_buckets = parse_bucket_selection(args.buckets)

    if args.symbols:
        symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    else:
        desired_bases = bucket_base_assets(leverage_buckets, selected_buckets)
        symbols = [
            s
            for s in available_symbols
            if s.endswith("USDT") and s.replace("/", "").split("USDT")[0].upper() in desired_bases
        ]

    symbols = sorted(set(symbols))
    if args.max_symbols and args.max_symbols > 0:
        symbols = symbols[: args.max_symbols]

    if args.btc_symbol not in available_symbols:
        raise RuntimeError(f"BTC regime symbol {args.btc_symbol} not present in DB")

    partial_levels = tuple(normalize_percent_to_ratio(v) for v in parse_float_csv(args.partial_levels, "partial-levels"))
    partial_sizes = tuple(normalize_percent_to_ratio(v) for v in parse_float_csv(args.partial_sizes, "partial-sizes"))

    config = BacktestConfig(
        initial_balance=float(args.initial_balance),
        signal_source=str(args.signal_source).strip().lower(),
        signal_wma_period=int(args.signal_wma_period),
        signal_wma_offset=int(args.signal_wma_offset),
        btc_regime_source=str(args.btc_regime_source).strip().lower(),
        btc_regime_wma_period=int(args.btc_regime_wma_period),
        btc_regime_wma_offset=int(args.btc_regime_wma_offset),
        atr_period=int(args.atr_period),
        atr_volatility_cutoff=max(0.0, normalize_percent_to_ratio(float(args.atr_volatility_cutoff_pct))),
        atr_size_scalar=float(args.atr_size_scalar),
        hard_stop_pct=abs(normalize_percent_to_ratio(float(args.hard_stop_pct))),
        trailing_trigger_pct=max(0.0, normalize_percent_to_ratio(float(args.trailing_activation_pct))),
        trailing_buffer_pct=max(0.0, normalize_percent_to_ratio(float(args.trailing_callback_pct))),
        partial_levels=partial_levels,
        partial_sizes=partial_sizes,
        max_hold_minutes=max(1, int(float(args.time_exit_hours) * 60.0)),
        macd_fast_period=int(args.macd_fast),
        macd_slow_period=int(args.macd_slow),
        macd_signal_period=int(args.macd_signal),
        stoch_rsi_period=int(args.stoch_rsi_period),
        stoch_rsi_k_period=int(args.stoch_rsi_k),
        stoch_rsi_d_period=int(args.stoch_rsi_d),
        require_macd_confirmation=bool(args.confirm_macd),
        require_stoch_rsi_confirmation=bool(args.confirm_stoch_rsi),
    )
    validate_backtest_config(config)

    runner = BacktestRunner(
        store=store,
        category=args.category,
        interval=args.interval,
        symbols=symbols,
        btc_symbol=args.btc_symbol,
        start_ms=args.start_ms,
        end_ms=args.end_ms,
        leverage_buckets=leverage_buckets,
        config=config,
    )

    summary = runner.run()

    out_dir = Path(args.out_dir)
    metadata = {
        "db": str(Path(args.db).resolve()),
        "category": args.category,
        "interval": args.interval,
        "recipe": args.recipe,
        "symbols": symbols,
        "selected_buckets": selected_buckets,
        "leverage_buckets": {
            "major": {
                "leverage": leverage_buckets["major"]["leverage"],
                "symbols": sorted(leverage_buckets["major"]["symbols"]),
            },
            "large_alt": {
                "leverage": leverage_buckets["large_alt"]["leverage"],
                "symbols": sorted(leverage_buckets["large_alt"]["symbols"]),
            },
            "mid_cap": {
                "leverage": leverage_buckets["mid_cap"]["leverage"],
                "symbols": sorted(leverage_buckets["mid_cap"]["symbols"]),
            },
            "default_leverage": leverage_buckets["default_leverage"],
        },
        "btc_symbol": args.btc_symbol,
        "start_ms": args.start_ms,
        "end_ms": args.end_ms,
        "config": dataclasses.asdict(config),
        "script": "backtest_aribot.py",
    }

    write_backtest_artifacts(
        out_dir=out_dir,
        summary=summary,
        trades=runner.closed_trades,
        equity_curve=runner.equity_curve,
        metadata=metadata,
    )

    print("Backtest complete")
    print(f"  symbols: {len(symbols)}")
    print(f"  closed_trades: {summary['closed_trades']}")
    print(f"  final_balance: {summary['final_balance']:.4f}")
    print(f"  total_return: {summary['total_return'] * 100:.2f}%")
    print(f"  max_drawdown: {summary['max_drawdown'] * 100:.2f}%")
    print(f"  artifacts: {out_dir.resolve()}")

    store.close()


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    argv_tokens = list(argv) if argv is not None else sys.argv[1:]
    parser = argparse.ArgumentParser(description="Aribot historical data + backtest pipeline")
    sub = parser.add_subparsers(dest="command", required=True)

    p_backfill = sub.add_parser("backfill", help="Backfill Bybit candles into SQLite")
    p_backfill.add_argument("--db", default="aribot_backtest.db", help="SQLite DB path")
    p_backfill.add_argument("--category", default="linear", help="Bybit category")
    p_backfill.add_argument("--interval", default=DEFAULT_INTERVAL, help="Bybit interval (240=4h)")
    p_backfill.add_argument("--symbols", default="", help="Optional comma-separated symbols (e.g. BTCUSDT,ETHUSDT)")
    p_backfill.add_argument(
        "--buckets",
        default="",
        help="Optional comma-separated leverage buckets from leverage_buckets.json: major,large_alt,mid_cap",
    )
    p_backfill.add_argument("--include-all-linear", action="store_true", help="Include all USDT linear perpetual symbols")
    p_backfill.add_argument("--only-trading", action="store_true", help="Only include instruments where status=Trading")
    p_backfill.add_argument("--start-ms", type=int, default=None, help="Optional global start timestamp (ms)")
    p_backfill.add_argument("--end-ms", type=int, default=None, help="Optional global end timestamp (ms)")
    p_backfill.add_argument("--limit", type=int, default=1000, help="Kline rows per request (<=1000)")
    p_backfill.add_argument("--sleep-seconds", type=float, default=0.05, help="Sleep between requests")
    p_backfill.add_argument("--max-pages", type=int, default=0, help="Optional cap per symbol (0=unlimited)")
    p_backfill.add_argument("--timeout-seconds", type=float, default=20.0, help="HTTP timeout")
    p_backfill.add_argument("--max-retries", type=int, default=8, help="Retries per API request on rate limit/transient errors")
    p_backfill.add_argument("--retry-base-seconds", type=float, default=1.0, help="Initial retry backoff seconds")
    p_backfill.add_argument("--retry-max-seconds", type=float, default=30.0, help="Maximum retry backoff seconds")
    p_backfill.add_argument("--testnet", action="store_true", help="Use Bybit testnet base URL")
    p_backfill.add_argument("--manifest-label", default="", help="Label embedded in dataset manifest")
    p_backfill.add_argument("--out-dir", default="backtest_artifacts/manifests", help="Where to write manifest JSON")
    p_backfill.add_argument("--leverage-config", default="leverage_buckets.json", help="Leverage bucket JSON path")

    p_run = sub.add_parser("run", help="Run deterministic backtest from local DB")
    p_run.add_argument("--recipe", choices=["baseline"], default="", help="Apply a preset strategy recipe")
    p_run.add_argument("--db", default="aribot_backtest.db", help="SQLite DB path")
    p_run.add_argument("--category", default="linear", help="Bybit category")
    p_run.add_argument("--interval", default=DEFAULT_INTERVAL, help="Bybit interval")
    p_run.add_argument("--symbols", default="", help="Optional comma-separated symbols; default uses leverage buckets")
    p_run.add_argument(
        "--buckets",
        default="",
        help="Optional comma-separated leverage buckets from leverage_buckets.json: major,large_alt,mid_cap",
    )
    p_run.add_argument("--max-symbols", type=int, default=0, help="Optional cap on symbol count")
    p_run.add_argument("--btc-symbol", default="BTCUSDT", help="BTC regime symbol")
    p_run.add_argument("--start-ms", type=int, default=None, help="Backtest start timestamp ms")
    p_run.add_argument("--end-ms", type=int, default=None, help="Backtest end timestamp ms")
    p_run.add_argument("--initial-balance", type=float, default=400.0, help="Initial balance")
    p_run.add_argument(
        "--signal-source",
        default="ohlc4",
        choices=["open", "high", "low", "close", "hl2", "hlc3", "ohlc4"],
        help="Signal source series used for strategy WMA, MACD, and Stoch RSI",
    )
    p_run.add_argument("--signal-wma-period", type=int, default=45, help="Signal WMA period")
    p_run.add_argument("--signal-wma-offset", type=int, default=2, help="Signal WMA offset")
    p_run.add_argument(
        "--btc-regime-source",
        default="ohlc4",
        choices=["open", "high", "low", "close", "hl2", "hlc3", "ohlc4"],
        help="BTC regime source series used for regime WMA",
    )
    p_run.add_argument("--btc-regime-wma-period", type=int, default=90, help="BTC regime WMA period")
    p_run.add_argument("--btc-regime-wma-offset", type=int, default=0, help="BTC regime WMA offset")
    p_run.add_argument("--hard-stop-pct", type=float, default=2.5, help="Hard stop percent (2.5 means 2.5%%)")
    p_run.add_argument(
        "--partial-levels",
        default="2,3,5",
        help="Comma-separated partial exit levels in percent or ratio (e.g. 2,3,5 or 0.02,0.03,0.05)",
    )
    p_run.add_argument(
        "--partial-sizes",
        default="25,25,25",
        help="Comma-separated partial exit sizes in percent or ratio (e.g. 25,25,25 or 0.25,0.25,0.25)",
    )
    p_run.add_argument(
        "--trailing-activation-pct",
        type=float,
        default=2.0,
        help="Trailing activation percent gain (2 means +2%%)",
    )
    p_run.add_argument(
        "--trailing-callback-pct",
        type=float,
        default=1.5,
        help="Trailing callback percent from peak/trough (1.5 means 1.5%%)",
    )
    p_run.add_argument("--time-exit-hours", type=float, default=40.0, help="Maximum hold time in hours")
    p_run.add_argument("--atr-period", type=int, default=14, help="ATR period")
    p_run.add_argument(
        "--atr-volatility-cutoff-pct",
        type=float,
        default=5.0,
        help="ATR/current cutoff in percent or ratio where ATR risk scalar is applied",
    )
    p_run.add_argument("--atr-size-scalar", type=float, default=0.5, help="Risk scalar when ATR cutoff is exceeded")
    p_run.add_argument("--major-leverage", type=float, default=None, help="Override major bucket leverage")
    p_run.add_argument("--large-alt-leverage", type=float, default=None, help="Override large_alt bucket leverage")
    p_run.add_argument("--mid-cap-leverage", type=float, default=None, help="Override mid_cap bucket leverage")
    p_run.add_argument("--default-leverage", type=float, default=None, help="Override default leverage")
    p_run.add_argument("--macd-fast", type=int, default=2, help="MACD fast period")
    p_run.add_argument("--macd-slow", type=int, default=39, help="MACD slow period")
    p_run.add_argument("--macd-signal", type=int, default=6, help="MACD signal period")
    p_run.add_argument("--stoch-rsi-period", type=int, default=14, help="Stochastic RSI base RSI period")
    p_run.add_argument("--stoch-rsi-k", type=int, default=3, help="Stochastic RSI K smoothing period")
    p_run.add_argument("--stoch-rsi-d", type=int, default=3, help="Stochastic RSI D smoothing period")
    p_run.add_argument(
        "--confirm-macd",
        action="store_true",
        help="Require MACD(2,39,6) diff confirmation on the prior closed OHLC4 bar",
    )
    p_run.add_argument(
        "--confirm-stoch-rsi",
        action="store_true",
        help="Require Stochastic RSI(14,3,3) K/D confirmation on the prior closed OHLC4 bar",
    )
    p_run.add_argument("--out-dir", default="backtest_artifacts/latest_run", help="Output directory")
    p_run.add_argument("--leverage-config", default="leverage_buckets.json", help="Leverage bucket JSON path")

    parsed = parser.parse_args(argv_tokens)
    parsed._provided_flags = collect_provided_cli_flags(argv_tokens)
    apply_run_recipe(parsed)
    return parsed


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    try:
        if args.command == "backfill":
            if args.max_pages <= 0:
                args.max_pages = None
            fetch_and_store_full_history(args)
        elif args.command == "run":
            run_backtest(args)
        else:
            raise RuntimeError(f"Unsupported command: {args.command}")
        return 0
    except KeyboardInterrupt:
        print("Interrupted", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

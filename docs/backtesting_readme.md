# Aribot Backtesting README

backtest_aribot.py provides a two-stage historical pipeline:

1. backfill: fetches Bybit kline history into local SQLite and emits a dataset manifest.
2. run: executes a deterministic strategy backtest from local candles and emits run artifacts.

## Scope and Non-Goals

In scope:

1. Historical USDT linear perpetual kline ingestion from Bybit public endpoints.
2. Deterministic simulation of strategy logic against local candle data.
3. Reproducible artifact generation for audit and comparison.

Non-goals:

1. Live order placement.
2. Portfolio optimization or hyperparameter search.
3. Tick-level execution simulation.

## Strategy Snapshot (Implemented Behavior)

The backtest runner mirrors the script logic as implemented in backtest_aribot.py.

- Signal source: OHLC4
- Main signal indicator: WMA period 45 with offset 2
- Regime filter: BTC symbol regime from WMA period 90 with offset 0
- Hard stop: -2.5%
- Partial profit levels: +2%, +3%, +5%
- Partial sizing: 25%, 25%, 25%
- Trailing activation: +2%
- Trailing callback buffer: 1.5%
- Time exit: 40 hours
- ATR controls:
  - ATR period 14
  - Volatility cutoff ratio 0.05
  - Position size scalar 0.5 when above cutoff
- Position limits and risk gates:
  - Initial balance 400.0 (overridable via CLI)
  - Max open positions 10
  - Entry risk percent 0.11
  - Daily drawdown limit -5%
  - Max consecutive losses 3
  - Cooldown 2 candles

## Inputs and Dependencies

Runtime requirements:

1. Python 3.10+
2. requests
3. Standard library modules used by the script (argparse, sqlite3, csv, json, hashlib, dataclasses, etc.)

Input files:

1. leverage_buckets.json (default path: leverage_buckets.json)
2. SQLite DB file (default path: aribot_backtest.db)

Network dependency:

1. backfill mode calls Bybit public APIs:
   - /v5/market/instruments-info
   - /v5/market/kline

Database assumptions:

1. backfill mode creates required tables if missing.
2. run mode expects candles to already exist in the selected db/category/interval.

## CLI Reference

Command form:

python backtest_aribot.py <subcommand> [flags]

### Subcommand: backfill

| Flag | Type | Default | Required | Description | Example |
| --- | --- | --- | --- | --- | --- |
| --db | str | aribot_backtest.db | no | SQLite DB path | --db aribot_backtest.db |
| --category | str | linear | no | Bybit market category | --category linear |
| --interval | str | 240 | no | Bybit kline interval (240 = 4h) | --interval 240 |
| --symbols | str | "" | no | Comma-separated symbol override | --symbols BTCUSDT,ETHUSDT |
| --buckets | str | "" | no | Comma-separated leverage buckets: major,large_alt,mid_cap | --buckets major,large_alt |
| --include-all-linear | bool flag | false | no | Include all USDT linear perpetuals | --include-all-linear |
| --only-trading | bool flag | false | no | Restrict instruments to status=Trading | --only-trading |
| --start-ms | int | None | no | Global start timestamp in ms | --start-ms 1704067200000 |
| --end-ms | int | None | no | Global end timestamp in ms | --end-ms 1735689599000 |
| --limit | int | 1000 | no | Rows per kline request (<=1000) | --limit 1000 |
| --sleep-seconds | float | 0.05 | no | Sleep between API requests | --sleep-seconds 0.1 |
| --max-pages | int | 0 | no | Per-symbol page cap (0 means unlimited) | --max-pages 500 |
| --timeout-seconds | float | 20.0 | no | HTTP timeout | --timeout-seconds 30 |
| --max-retries | int | 8 | no | Retry count for transient/rate-limit errors | --max-retries 10 |
| --retry-base-seconds | float | 1.0 | no | Initial retry backoff seconds | --retry-base-seconds 1 |
| --retry-max-seconds | float | 30.0 | no | Maximum retry backoff seconds | --retry-max-seconds 60 |
| --testnet | bool flag | false | no | Use Bybit testnet base URL | --testnet |
| --manifest-label | str | "" | no | Free-form label embedded in dataset manifest | --manifest-label major-2026q1 |
| --out-dir | str | backtest_artifacts/manifests | no | Dataset manifest output directory | --out-dir backtest_artifacts/manifests |
| --leverage-config | str | leverage_buckets.json | no | Leverage bucket JSON path | --leverage-config leverage_buckets.json |

### Subcommand: run

| Flag | Type | Default | Required | Description | Example |
| --- | --- | --- | --- | --- | --- |
| --db | str | aribot_backtest.db | no | SQLite DB path | --db aribot_backtest.db |
| --category | str | linear | no | Candle category filter | --category linear |
| --interval | str | 240 | no | Candle interval filter | --interval 240 |
| --symbols | str | "" | no | Comma-separated symbol override | --symbols BTCUSDT,ETHUSDT |
| --buckets | str | "" | no | Comma-separated leverage buckets: major,large_alt,mid_cap | --buckets major,large_alt |
| --max-symbols | int | 0 | no | Symbol cap (0 means no cap) | --max-symbols 20 |
| --btc-symbol | str | BTCUSDT | no | BTC regime symbol required in DB | --btc-symbol BTCUSDT |
| --start-ms | int | None | no | Backtest start timestamp in ms | --start-ms 1704067200000 |
| --end-ms | int | None | no | Backtest end timestamp in ms | --end-ms 1735689599000 |
| --initial-balance | float | 400.0 | no | Starting equity | --initial-balance 1000 |
| --out-dir | str | backtest_artifacts/latest_run | no | Run artifact output directory | --out-dir backtest_artifacts/major_run |
| --leverage-config | str | leverage_buckets.json | no | Leverage bucket JSON path | --leverage-config leverage_buckets.json |

## Quickstart

### 1) Environment setup

Windows PowerShell:

python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

Linux/macOS shell:

python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

### 2) Backfill historical candles

Example A: bucket-driven symbol selection

python backtest_aribot.py backfill --db aribot_backtest.db --category linear --interval 240 --buckets major,large_alt --only-trading --manifest-label major-largealt-4h

Example B: explicit symbol universe with fixed window

python backtest_aribot.py backfill --db aribot_backtest.db --category linear --interval 240 --symbols BTCUSDT,ETHUSDT,SOLUSDT --start-ms 1704067200000 --end-ms 1735689599000 --manifest-label explicit-2024

### 3) Run deterministic backtest

python backtest_aribot.py run --db aribot_backtest.db --category linear --interval 240 --buckets major,large_alt --btc-symbol BTCUSDT --initial-balance 400 --out-dir backtest_artifacts/latest_run

### 4) Inspect outputs

Expected files under the selected out-dir:

1. summary.json
2. trades.csv
3. equity_curve.csv
4. run_manifest.json

## Reproducibility Contract

To make runs comparable and repeatable:

1. Pin data window with both --start-ms and --end-ms.
2. Pin universe using --symbols or a fixed --buckets set.
3. Pin leverage config file and keep it version-controlled.
4. Keep db/category/interval identical across compared runs.
5. Persist and compare manifest hash values:
   - Dataset hash in dataset manifest from backfill.
   - Run hash in run_manifest.json from run.
6. Keep initial balance constant when comparing strategy behavior.

Non-deterministic factors to control:

1. Ongoing data ingestion can change the dataset if end-ms is open-ended.
2. API availability/rate-limit behavior can affect backfill completion time.

## Output Artifacts

### summary.json

Path:

<out-dir>/summary.json

Contains:

- initial_balance
- final_balance
- total_pnl
- total_return
- closed_trades
- win_rate
- winning_trades
- losing_trades
- max_drawdown
- reason_counts
- metadata (db path, category, interval, symbols, buckets, config, script)

### trades.csv

Path:

<out-dir>/trades.csv

Columns:

- symbol
- side
- entry_time_ms
- exit_time_ms
- entry_price
- exit_price
- quantity
- pnl
- pnl_pct
- reason
- leverage
- leverage_tier
- partials_json

### equity_curve.csv

Path:

<out-dir>/equity_curve.csv

Columns:

- time_ms
- balance
- unrealized_pnl
- equity

### run_manifest.json

Path:

<out-dir>/run_manifest.json

Contains:

- created_at_utc
- run_sha256
- summary_path
- trades_path
- equity_curve_path
- metadata

## Validation Checklist

Use this checklist before trusting a run:

- [ ] Backfill command exited with code 0.
- [ ] Run command exited with code 0.
- [ ] Selected symbol universe matches intended symbols/buckets.
- [ ] BTC regime symbol exists in the local DB for the selected category/interval.
- [ ] run_manifest.json contains run_sha256.
- [ ] summary.json and trades.csv agree on closed trade count.
- [ ] final_balance is plausible relative to initial_balance and total_pnl.

## Known Limitations

1. Uses candle-level fills and cannot model intrabar path dependency.
2. Backfill uses public API data quality as-is.
3. Slippage and fee assumptions are simplified into a round-trip fee model.
4. run subcommand fails if DB has no candles for selected category/interval.

## Troubleshooting

Symptom: ERROR RuntimeError: No candles found in DB. Run backfill first.

- Cause: The selected DB/category/interval has no candle rows.
- Fix: Run backfill with matching --db, --category, and --interval.

Symptom: ERROR RuntimeError: BTC regime symbol BTCUSDT not present in DB

- Cause: BTC regime series was not ingested for selected DB filters.
- Fix: Backfill BTCUSDT or run with a btc-symbol that exists in DB.

Symptom: Very few symbols selected in backfill

- Cause: Bucket filter, only-trading, or include-all-linear settings are restrictive.
- Fix: Use --include-all-linear or broaden --buckets / --symbols.

Symptom: Backfill is slow or retries frequently

- Cause: API rate limiting or network instability.
- Fix: Increase --sleep-seconds, tune retry flags, and reduce symbol scope.

## Change Log Notes

- 2026-04-08: Initial backtesting README created and aligned to current backtest_aribot.py CLI and artifact behavior.

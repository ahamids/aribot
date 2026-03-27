# Aribot

Aribot is a Python trading bot project for Bybit perpetuals with three layers of functionality:

1. A currently runnable paper-style strategy loop in [usdt_paper_bot_v2.py](usdt_paper_bot_v2.py)
2. Live-trading safety scaffolding such as secrets validation, startup reconciliation, observability, deployment docs, and idempotent order submission helpers
3. Validation and go-live documentation for promoting from testnet to mainnet

The default runnable path today is still the paper-style simulator. The repo also includes the infrastructure needed to harden a future live execution path.

## Quick Start

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install ccxt requests
Copy-Item .env.example .env
python usdt_paper_bot_v2.py
```

## Current State

What is implemented now:

1. Paper-style position simulation on Bybit market data
2. SQLite persistence and restart recovery
3. Risk controls including daily drawdown pause, cooldown, stop-loss checks, trailing stop, partial exits, and time exit
4. Startup secret validation for authenticated modes
5. Startup reconciliation gate for authenticated modes
6. Structured logs, funding tracking, Telegram alert routing, and kill switch support
7. Validation scripts and a go-live runbook

What is not fully implemented yet:

1. Full live order lifecycle management for partial fills and terminal exchange order states
2. End-to-end real Telegram delivery verification in this repo by default
3. A complete live execution engine wired into the main strategy loop

## Repository Layout

Key files:

1. [usdt_paper_bot_v2.py](usdt_paper_bot_v2.py): main runnable bot for USDT markets
2. [usdc_paper_bot_v2.py](usdc_paper_bot_v2.py): older USDC variant
3. [secret_loader.py](secret_loader.py): environment and Bybit permission validation
4. [startup_reconciler.py](startup_reconciler.py): authenticated startup reconciliation gate
5. [observability.py](observability.py): structured events, kill switch monitor, funding tracker
6. [order_executor.py](order_executor.py): order helper with idempotency ledger
7. [verify_bot_v2.py](verify_bot_v2.py): deterministic verification harness
8. [test_live_bot.py](test_live_bot.py): validation suite for safety and operational checks
9. [.env.example](.env.example): sample runtime configuration
10. [docs/go_live_runbook.md](docs/go_live_runbook.md): staged promotion process
11. [docs/deployment_checklist.md](docs/deployment_checklist.md): deployment steps

## Requirements

1. Python 3.11+ recommended
2. `ccxt`
3. `requests`

Install dependencies:

```bash
pip install ccxt requests
```

## Getting Started

### 1. Clone and open the repo

```bash
git clone <your-repo-url>
cd aribot
```

### 2. Create and activate a virtual environment

Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

### 3. Install dependencies

```bash
pip install ccxt requests
```

### 4. Create your env file

Copy [.env.example](.env.example) to `.env` and update the values.

Windows PowerShell:

```powershell
Copy-Item .env.example .env
```

Important:

1. `.env` is ignored by git
2. `.env.example` should stay as placeholders only
3. For `paper` mode, placeholder API keys can remain unused
4. For `shadow` and `live`, valid Bybit keypairs are required

### 5. Choose a mode

Mode behavior is currently:

1. `paper`
   Uses market data and local simulation only
   No authenticated startup reconciliation
   No Bybit credentials required to start
2. `shadow`
   Requires validated Bybit keypairs
   Runs startup permission checks and startup reconciliation
   Intended for authenticated non-promoted operation
3. `live`
   Same startup requirements as `shadow`
   Reserved for the real-money promotion path described in the runbook

## Environment Setup

The sample env file is documented in [.env.example](.env.example).

Important variables:

1. `BOT_MODE`
   One of `paper`, `shadow`, or `live`
2. `BYBIT_TESTNET`
   `true` for testnet, `false` for mainnet
3. `KILL_SWITCH_FILE`
   File path watched by the kill switch monitor
4. `BYBIT_READ_API_KEY` and `BYBIT_READ_API_SECRET`
   Required for `shadow` and `live`
5. `BYBIT_TRADE_API_KEY` and `BYBIT_TRADE_API_SECRET`
   Required for `shadow` and `live`
   Withdrawal permission must be disabled
6. `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`
   Optional, only needed if you want Telegram alert delivery

## Running the Bot

Default run command:

```bash
python usdt_paper_bot_v2.py
```

The bot will:

1. Validate startup secrets
2. Load markets and leverage config
3. In `shadow` or `live`, run authenticated startup reconciliation
4. Start the main loop

Stop with `Ctrl+C`.

Runtime artifacts:

1. SQLite database: `usdt_paper_bot_v2.db`
2. Runtime log: `usdt_paper_trading_log.txt`
3. Structured events: `observability.jsonl`

## Strategy Summary

The active strategy loop currently:

1. Uses 4-hour candles and OHLC4 price source
2. Computes `WMA(45)` with offset `2`
3. Applies BTC regime gating
4. Evaluates new entries near 4-hour UTC boundaries
5. Simulates position sizing using leverage buckets from [leverage_buckets.json](leverage_buckets.json)
6. Manages open positions with:
   - stop-loss checks
   - trailing stop logic
   - partial profit taking
   - time exit
   - daily drawdown pause
   - consecutive-loss cooldown

## Validation and Verification

### Verify core logic

```bash
python verify_bot_v2.py --market usdt
```

Strict mode:

```bash
python verify_bot_v2.py --market usdt --strict
```

This checks:

1. Signal-window behavior
2. ATR calculation
3. Fee-adjusted PnL logic
4. Time exit logic
5. Daily drawdown breaker logic
6. Cooldown logic
7. Expected log markers

### Run the live validation suite

```bash
python test_live_bot.py
```

This currently validates:

1. Startup ghost-position blocking behavior
2. Kill switch shutdown path
3. Funding PnL deduction path
4. `DRY_RUN` protection
5. Idempotency duplicate suppression
6. Stop-loss checks per update cycle
7. Telegram alert routing logic

The real Bybit order-placement test is skipped unless valid testnet credentials are present in the environment.

## Deployment and Go-Live Docs

Deployment and promotion references:

1. [docs/deployment_checklist.md](docs/deployment_checklist.md)
2. [docs/go_live_runbook.md](docs/go_live_runbook.md)
3. [docs/branching_strategy.md](docs/branching_strategy.md)

## Notes and Caveats

1. The main strategy file still simulates positions locally. It is not yet a fully wired live order-management runtime.
2. `shadow` and `live` currently differ mainly in startup safety expectations and promotion intent, not in a separate execution engine inside the main loop.
3. If you run in `paper`, authenticated startup reconciliation is intentionally skipped.
4. If you run in `shadow` or `live`, valid Bybit credentials must be configured or startup will fail.

## Troubleshooting

### Missing credentials

Symptom:

```text
Startup validation failed: Missing required environment variables: ...
```

Cause:

1. `BOT_MODE` is `shadow` or `live`
2. One or more required Bybit env vars are empty

Fix:

1. Open `.env`
2. Set all required values:
   - `BYBIT_READ_API_KEY`
   - `BYBIT_READ_API_SECRET`
   - `BYBIT_TRADE_API_KEY`
   - `BYBIT_TRADE_API_SECRET`
3. If you only want local simulation, set `BOT_MODE=paper`

### Kill switch present at startup

Symptom:

```text
Startup validation failed: Kill switch file detected at startup: ...
```

Cause:

1. The file referenced by `KILL_SWITCH_FILE` exists

Fix:

1. Remove the kill switch file
2. Confirm `.env` points to the expected path
3. Restart the bot

### Startup reconciliation block

Symptom:

```text
Startup reconciliation failed: Startup reconciliation failed. Manual review required before main loop can start.
```

Cause:

1. You are running in `shadow` or `live`
2. The reconciler detected a ghost position or another startup mismatch requiring manual review

Fix:

1. Review the latest reconciliation entries in the SQLite database
2. Inspect `observability.jsonl` and `usdt_paper_trading_log.txt`
3. Resolve the exchange-vs-local mismatch before restarting
4. Do not bypass this in `shadow` or `live`

### Bybit authentication error in paper mode

Symptom:

```text
ccxt.base.errors.AuthenticationError: bybit requires "apiKey" credential
```

Cause:

1. This should not happen in current `paper` mode startup
2. It usually means you are not actually running with `BOT_MODE=paper`, or a different authenticated path was introduced

Fix:

1. Confirm `.env` has `BOT_MODE=paper`
2. Re-run with the current code from this repo
3. If it still happens, inspect recent changes around startup reconciliation and exchange initialization

### Telegram alerts not sending

Symptom:

1. Bot runs normally
2. No Telegram alerts arrive

Cause:

1. `TELEGRAM_BOT_TOKEN` or `TELEGRAM_CHAT_ID` is missing or invalid
2. Network access to Telegram failed

Fix:

1. Set `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` in `.env`
2. Restart the bot
3. Trigger a known alert path such as `position_opened` or kill switch detection

### Test suite skips real exchange order test

Symptom:

```text
[1] Order placement on Bybit testnet: SKIP
```

Cause:

1. Testnet trading credentials are not set in the environment

Fix:

1. Set `BYBIT_TRADE_API_KEY` and `BYBIT_TRADE_API_SECRET`
2. Also set `TESTNET_SYMBOL` and `TESTNET_ORDER_QTY` before running `python test_live_bot.py`

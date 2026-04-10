# Aribot

Aribot now boots through `main.py` (thin entrypoint) and delegates runtime work to modular bootstrap code under `aribot/`.
The packaged runtime engine now lives under `aribot/runtime/engine.py`.

Emoji output mode:
- Default is `noemojis` (no emoji characters in console/text log output).
- Use `--emojis` to keep emoji output enabled.
- JSON structured logging in `observability.jsonl` is unchanged by this flag.

Examples:
- `python main.py`
- `python main.py --profile usdt`
- `python main.py --profile usdc`
- `python main.py --mode shadow`
- `python main.py --emojis`

This README is operator-focused and reflects implemented behavior in code.

## Quickstart

### 1) Install

Requirements:

1. Python 3.10+.
2. `pip` (usually included with Python).
3. Project dependencies: `ccxt`, `requests`, `python-dotenv`, `pyyaml`.

Windows (PowerShell):

```powershell
# Verify Python is installed. If this fails, install Python from python.org first.
python --version

python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install ccxt requests python-dotenv pyyaml
Copy-Item .env.example .env
```

Linux server (Ubuntu/Debian):

```bash
# Install Python and venv tooling if missing
sudo apt-get update
sudo apt-get install -y python3 python3-venv python3-pip

python3 --version

python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install ccxt requests python-dotenv pyyaml
cp .env.example .env
```

### 2) Choose mode

`BOT_MODE` supports:

1. `paper`: local simulation from market data.
2. `shadow`: authenticated startup + reconciliation enabled, executor forced to dry-run behavior.
3. `live`: authenticated startup + reconciliation + exchange order submission enabled.

### 3) Run

```bash
python main.py
```

## Required Environment

Minimum practical env (edit `.env`):

```dotenv
BOT_MODE=paper
BYBIT_TESTNET=true
KILL_SWITCH_FILE=kill_switch.flag

BYBIT_READ_API_KEY=
BYBIT_READ_API_SECRET=
BYBIT_TRADE_API_KEY=
BYBIT_TRADE_API_SECRET=

TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
TELEGRAM_VERIFY_ON_START=true

DRY_RUN=false
ORDER_STATUS_TIMEOUT_SECONDS=30
ORDER_STATUS_POLL_INTERVAL_SECONDS=1.5
ORDER_EXECUTOR_DB=usdt_bot_v2.db
```

Mode semantics:

1. In `shadow` and `live`, both keypairs are required and validated.
2. `secret_loader.py` checks Bybit key metadata via signed `GET /v5/user/query-api` calls.
3. Startup rejects keys that appear to have withdraw permission.
4. In `live`, if `TELEGRAM_VERIFY_ON_START=true`, Telegram startup verification failure aborts startup.

## What Runs at Startup

1. Parse env and mode.
2. Validate secrets and kill switch file.
3. Build bot components (exchange client, DB, observability, reconciler).
4. In `shadow`/`live`, run startup reconciliation gate before entering loop.
5. Optionally run Telegram delivery readiness check.
6. Enter main loop (`60` second cadence).

## Phase 1 Parity Baseline

Run deterministic characterization tests before refactors:

```bash
python -m unittest tests.parity.test_usdt_characterization -v
```

Existing verification harness remains available:

```bash
python verify_bot_v2.py --market usdt
```

Plugin IDs are now config-driven in `config/bot.yaml` and profile files:

```yaml
plugins:
   exchange: bybit
   strategy: wma45_ohlc4
   regime_filter: wma_regime
   risk: default_risk
```

At startup, `main.py` bootstrap resolves these IDs, validates availability,
and instantiates runtime plugin shims bound to the current bot context.
These shims are exposed through a runtime execution context used by the loop
for symbol selection, regime updates, risk gates, strategy analysis, and
exchange data fetch operations.

## Extending the Bot (Exchanges, Strategies, Indicators)

This section is implementation-focused and follows the current code path in:
- `aribot/plugins/registry.py`
- `aribot/plugins/factory.py`
- `aribot/adapters/`
- `aribot/domain/indicators.py`

### Add a new exchange plugin

Goal: make `plugins.exchange: <your_exchange_id>` valid in config.

1. Create a new adapter file under `aribot/adapters/`.
   - Example: `aribot/adapters/exchange_binance.py`
2. Implement methods used by runtime context:
   - `name(self) -> str`
   - `list_symbols(self) -> list[str]`
   - `fetch_ticker(self, symbol)`
   - `fetch_ohlcv(self, symbol, timeframe, limit=100)`
   - `fetch_balance(self)`
3. Register the plugin id in `aribot/plugins/registry.py` inside `build_builtin_registry()`.
4. Wire construction in `aribot/plugins/factory.py`:
   - add import for your adapter
   - extend `_build_exchange(...)` with your id
5. Update config to select it:
   - `config/bot.yaml` or `config/profiles/<profile>.yaml`
   - set `plugins.exchange: <your_exchange_id>`
6. Validate:

```bash
python -m unittest discover -s tests/parity
python verify_bot_v2.py --market usdt
```

Minimal skeleton:

```python
from __future__ import annotations


class BinanceExchangeAdapter:
   def __init__(self, bot):
      self.bot = bot

   def name(self) -> str:
      return "binance"

   def list_symbols(self) -> list[str]:
      return list(getattr(self.bot, "quote_swaps", []))

   def fetch_ticker(self, symbol: str):
      return self.bot.exchange.fetch_ticker(symbol)

   def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int = 100):
      return self.bot.exchange.fetch_ohlcv(symbol, timeframe, limit=limit)

   def fetch_balance(self):
      return self.bot.exchange.fetch_balance()
```

### Add a new strategy plugin

Goal: make `plugins.strategy: <your_strategy_id>` valid and produce analysis payloads compatible with open/update flow.

Required return shape from `analyze_symbol(...)`:
- `symbol` (str)
- `current_price` (float)
- `signal` (`BUY` or `SELL`)
- `confirmed` (bool)
- optional: `atr_ratio` (float)

1. Create strategy adapter file under `aribot/adapters/`.
   - Example: `aribot/adapters/strategy_ema_cross.py`
2. Implement:
   - `name(self) -> str`
   - `required_candle_count(self) -> int`
   - `analyze_symbol(self, symbol: str, for_entry: bool = False)`
3. Register id in `aribot/plugins/registry.py`.
4. Wire `_build_strategy(...)` in `aribot/plugins/factory.py`.
5. Select in config:
   - `plugins.strategy: <your_strategy_id>`
6. Validate with parity tests.

Minimal skeleton:

```python
from __future__ import annotations

from aribot.domain.indicators import calculate_ohlc4


class EMACrossStrategyAdapter:
   def __init__(self, bot):
      self.bot = bot

   def name(self) -> str:
      return "ema_cross"

   def required_candle_count(self) -> int:
      return 120

   def analyze_symbol(self, symbol: str, for_entry: bool = False):
      ohlcv = self.bot.fetch_symbol_ohlcv(symbol, "4h", limit=120)
      if not ohlcv or len(ohlcv) < self.required_candle_count():
         return None

      ohlc4 = calculate_ohlc4(ohlcv)
      current_price = float(ohlc4[-1])

      # Replace with your own fast/slow EMA logic.
      signal = "BUY"
      confirmed = True

      return {
         "symbol": symbol,
         "current_price": current_price,
         "signal": signal,
         "confirmed": confirmed,
         "atr_ratio": 0.0,
      }
```

### Add a new indicator (currently WMA + OHLC4)

Indicators live in `aribot/domain/indicators.py` and should be pure functions.

1. Add your function to `aribot/domain/indicators.py`.
   - Keep it stateless and deterministic.
2. Import and use it from your strategy adapter.
3. Add or update parity/unit tests for the new indicator behavior.

Example indicator:

```python
def calculate_ema(source_prices, period: int):
   if len(source_prices) < period:
      return None
   k = 2 / (period + 1)
   ema = float(source_prices[0])
   for price in source_prices[1:]:
      ema = float(price) * k + ema * (1 - k)
   return ema
```

### Common failure modes checklist

1. `Unknown <kind> plugin` at startup
   - Plugin id not registered in `build_builtin_registry()` or not wired in factory.
2. Entry scan runs but no positions open
   - Strategy adapter returns missing fields or `confirmed=False`.
3. Runtime fallback unexpectedly used
   - Adapter method raises exception; execution context falls back by design.
4. Tests pass locally but startup fails
   - Config profile points to plugin id not available in registry/factory.

## Strategy (Implemented)

### Signal model

1. Candle timeframe: `4h`.
2. Price source: `OHLC4 = (O + H + L + C) / 4`.
3. Entry line: `WMA(45)` with offset `2`.
4. Regime filter: BTC OHLC4 vs BTC `WMA(200)`.
   - Above -> only `BUY` candidates.
   - Below -> only `SELL` candidates.
5. Confirmation rule (`confirm_signal`) requires consecutive directional context and breakout/breakdown close logic.

### Entry window and filters

1. Cycle `1` does a bootstrap entry scan.
2. Normal entry scans occur on 4h boundary windows.
3. Stale ticker filter: age must be `<= 600` seconds.
4. Frozen ticker filter: rejects repeated unchanged tick signatures after `2` cycles.
5. Entry volume filter: 24h quote volume must be `> 5_000_000`.

### Entry sizing

1. Base risk fraction: `0.11` of current balance.
2. ATR scalar rule: if `atr_ratio > 0.05`, risk is multiplied by `0.5`.
3. Leverage tiers (from bucket mapping):
   - major `5x`, large_alt `3x`, mid_cap `2x`, default `1x`.
4. Quantity is fee-adjusted with `round_trip_fee_rate = 0.0011`.

## Position Management

Per open position, each loop:

1. Reprice and recompute PnL.
2. Hard stop: close if pnl% `<= -2.5`.
3. Partial profits: levels `2%`, `3%`, `5%` with sizes `30%`, `30%`, `40%`.
4. Trailing stop activation: at `+2%` pnl.
5. Trailing callback buffer: `1.5%` from peak.
6. Close on trailing breach.
7. Time exit at `40` hours.

## SL/TP/Trailing on Exchange

`order_executor.py` uses CCXT-only trading-stop flow:

1. Native initial SL: `2.5%` from entry, MarkPrice trigger.
2. Native initial TP: `5%` from entry.
3. Native TP partial amount ratio default: `0.30`.
4. On trailing activation, bot requests native trailing callback `0.015` and clears fixed SL/TP.
5. Native protection failures are warning-only (non-blocking).

## Fill and PnL Handling

### Entry fill policy

In live execution, entry open requires confirmed exchange fill data:

1. Confirm from order/trade aggregation first.
2. Fallback confirmation from `fetch_position` snapshot.
3. If not confirmed, local position open is skipped to avoid incorrect SL/TP.

### Internal PnL formulas

1. Price-only pnl%:
   - long: `((current - entry) / entry) * 100`
   - short: `((entry - current) / entry) * 100`
2. Monetary PnL:
   - gross from price delta * quantity
   - fee cost = average notional * `0.0011`
   - net pnl = gross - fee cost

## Risk Controls

1. Daily drawdown breaker: pause entries when drawdown from session baseline is `<= -5%`.
2. Consecutive-loss cooldown: after `3` losses, pause entries for `2` candles (`8` hours).
3. Position cap: maximum `10` concurrent opens.
4. Kill switch:
   - startup refuses if `KILL_SWITCH_FILE` exists,
   - runtime triggers emergency close flow,
   - intentional shutdown code is `42`.

## Telegram Management Commands

Authorized operator chat can issue only the commands below:

1. `/status`
2. `/positions`
3. `/pnl`
4. `/trades [n]`
5. `/pause`
6. `/resume`
7. `/close SYMBOL`
8. `/close all`
9. `/kill`
10. `/config`

One-time command-menu registration (recommended for new deployments):

1. Run once after setting `TELEGRAM_BOT_TOKEN`:

```bash
python deploy/register_telegram_commands.py
```

2. Optional dry-run preview:

```bash
python deploy/register_telegram_commands.py --dry-run
```

Note: Telegram command menu entries are metadata and do not auto-populate from bot runtime code.
You can still type commands manually even before menu registration.

Command behavior:

1. `/trades [n]`
   - no argument: returns all closed trades from today (UTC)
   - with argument `n`: returns the latest `n` closed trades
2. `/pause` blocks new entries only; existing positions keep normal management.
3. `/resume` re-enables new entries.
4. `/config` is read-only and reports only:
   - mode
   - leverage buckets
   - position cap
   - stop %
5. `/config` never exposes secrets, API keys, bot token, chat id, or raw env values.

Confirmation-gated commands:

1. `/close SYMBOL`, `/close all`, and `/kill` require reply text exactly `YES` within the confirmation TTL window.
2. Any non-`YES` reply cancels the pending action.
3. A new dangerous command replaces the previous pending action.
4. Replay `YES` with no valid pending action returns `No pending confirmation.`
5. TTL is controlled by `TELEGRAM_CONFIRMATION_TTL_SECONDS` (default `90`, minimum `5`).

Kill command warning:

1. Confirmed `/kill` writes the kill switch flag, triggers close-all flow, and requests clean shutdown exit code `42`.
2. Restart requires explicit operator recovery: investigate incident, clear kill switch flag, then relaunch.

## Bybit Call Surface

### Read-side calls

1. `load_markets`
2. `fetch_ticker`
3. `fetch_ohlcv`
4. `fetch_balance` (live execution enabled)
5. `fetch_funding_rate`
6. `fetch_positions`, `fetch_my_trades` (reconciliation/fill paths)

### Order-side calls

1. `create_order` for entries/exits/partials.
2. `set_leverage` before entry orders.
3. `fetch_order` polling and `fetch_my_trades` fill summary.
4. Trading-stop via CCXT `create_order(..., params={'tradingStopEndpoint': True, ...})`.

## Persistence and Recovery

Main runtime DB: `usdt_bot_v2.db`.

Runtime tables:

1. `positions`
2. `closed_trades`
3. `partial_realizations`
4. `bot_state`
5. `funding_payments`
6. `reconciliation_reports`
7. `reconciliation_items`

Executor idempotency DB path comes from `ORDER_EXECUTOR_DB` (default `usdt_bot_v2.db`) and stores `order_idempotency`.

Recovery behavior:

1. Persisted positions are restored and repriced at startup.
2. Stop/exit conditions can trigger immediate close after restore.
3. In authenticated modes, startup reconciliation can block loop start when manual review is required.

## Verification

### Deterministic harness

```bash
python verify_bot_v2.py --market usdt
python verify_bot_v2.py --market usdt --strict
```

### Live/test harness

```bash
python test_live_bot.py
```

## Deployment (systemd)

Service file: `deploy/aribot.service`.

```bash
sudo cp deploy/aribot.service /etc/systemd/system/aribot.service
sudo systemctl daemon-reload
sudo systemctl enable aribot
sudo systemctl restart aribot
sudo systemctl status aribot
```

## Runtime Artifacts

1. Text log: `usdt_trading_log.txt`
2. Structured events: `observability.jsonl`
3. Runtime DB: `usdt_bot_v2.db`

## New Plugin PR Checklist

Use this checklist before opening a PR that adds or changes exchange/strategy/risk/regime plugins.

1. Create adapter file(s) under `aribot/adapters/` with required methods implemented.
2. Register plugin id(s) in `aribot/plugins/registry.py` via `build_builtin_registry()`.
3. Wire plugin construction in `aribot/plugins/factory.py`.
4. Update config selection in `config/bot.yaml` or `config/profiles/<profile>.yaml`.
5. Confirm runtime return shapes are compatible (`analyze_symbol` payload fields in particular).
6. Add or update parity/unit tests covering both plugin path and fallback path.
7. Run validation locally:

```bash
python -m unittest discover -s tests/parity
python verify_bot_v2.py --market usdt
```

8. Update README/docs for any new plugin IDs, config keys, or operational behavior.
9. Include a PR summary with: changed files, new plugin IDs, config diff, and test output.

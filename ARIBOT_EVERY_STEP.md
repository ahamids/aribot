## Full bot architecture — every step and component

### Startup sequence

**1. Argument parsing**
- Accepts `--symbols` (CSV) or `--symbols-file` (JSON) to optionally restrict the trading universe
- Accepts `--emojis`/`--noemojis` flag for log output mode

**2. Secret loading & validation**
- Loads API keys, bot mode (`paper`/`shadow`/`live`), and testnet flag from env/config
- Validates that required secrets are present before the bot is allowed to instantiate

**3. Exchange connection**
- Connects to Bybit via `ccxt`
- If testnet flag is set, enables sandbox mode on both the read client and the order executor

**4. Mode-aware client setup**
- `paper`: no real keys used, no orders sent
- `shadow`: orders submitted to the order executor but `dry_run=True` — intents logged, nothing hits exchange
- `live`: real keys, real orders

**5. Parameter initialization**
- Balance: $400 starting capital
- Max open positions: 10
- Entry risk: 11% of balance per trade
- ATR volatility scalar: halve size if ATR/price > 5%
- Leverage tiers loaded from `leverage_buckets.json` (falls back to hardcoded defaults: BTC/ETH=5x, large alts=3x, mid caps=2x, everything else=1x)
- Max hold: 40 hours
- Loop interval: 60 seconds
- Signal boundary window: 60 seconds around the 4H candle close
- Max ticker age: 600 seconds
- Max unchanged tick cycles before skip: 2

**6. Symbol universe construction**
- Fetches all markets from Bybit
- Filters to USDT perpetual swaps only
- If allowlist provided (CLI or file): filters down to matching symbols; warns on unmatched entries; aborts if result is empty
- Resolves the BTC regime symbol (prefers `BTC/USDT:USDT`)

**7. Database setup** (SQLite `usdt_bot_v2.db`)
- Creates tables: `positions`, `closed_trades`, `partial_realizations`, `bot_state`
- Runs column-level migrations for older DBs missing newer columns
- Creates reconciliation tables via `StartupReconciler`
- Creates funding tracking table via `FundingTracker`

**8. State restoration**
- Reloads all open positions from SQLite into memory (including partial exits, trailing stop state, native stop flags, and companion limit order id)
- Reconstructs cumulative stats (total trades, wins, losses, total PnL, balance) from closed trades + partial realizations
- Overrides with persisted `bot_state` values if present (for exact stop/restart continuity)
- Restores Telegram update offset, manual pause flag, and any pending confirmation nonces (discards expired ones)

**9. Live balance sync** (live/shadow only)
- Fetches real USDT balance from Bybit
- If no trades have happened yet and balance differs from the $400 default, rebases the daily drawdown baseline to the real balance

**10. Startup reconciliation gate** (live/shadow only)
- Fetches all open positions from exchange
- Compares against local SQLite state:
  - Local open, exchange flat → attempts to reconstruct close price from trade history; records as `unknown_close` if unavailable; alerts
  - Exchange open, local missing → CRITICAL alert, manual review required, bot blocks startup
  - Both open with >1% qty or entry price mismatch → WARNING, overwrites local with exchange truth
- Saves a full reconciliation report to SQLite
- If critical issues found: blocks the trading loop from starting

**11. Position recovery on startup**
- For each reloaded open position: fetches current price, updates PnL
- If the position already breached stop-loss or trailing stop: closes it immediately as `RECOVERY`
- If trailing stop should now be active: activates it

**12. Telegram delivery verification**
- Sends a startup probe message to configured chat ID
- In `live` mode: aborts if delivery fails
- In other modes: logs warning and continues

**13. Kill switch preflight**
- If `kill_switch.flag` file exists at startup: persists state and exits immediately without entering the loop

**14. Startup pulse**
- Sends an initial heartbeat message to Telegram with mode, balance, position count, and entry gate state

---

### Per-cycle loop (every 60 seconds)

**15. Kill switch check**
- Checks if `kill_switch.flag` exists on disk
- If found: cancels all open orders, closes all positions at market, requests clean shutdown, exits loop

**16. Shutdown flag check**
- Checks if `shutdown_requested` was set (e.g., by Telegram `/kill`); exits loop if so

**17. Scheduled pulse**
- Every 60 minutes: sends a heartbeat to Telegram with balance, session PnL, open positions, entry gate state

**18. Telegram command polling**
- Calls Telegram `getUpdates` with the persisted offset (long-poll timeout=0, up to 25 updates)
- Sorts updates by `update_id` to ensure ordered processing
- Routes each message to `route_telegram_command`
- Persists the next offset after each update to survive restarts
- **Authorization**: rejects messages from any chat ID other than the configured one
- **Confirmation gate**: `/close SYMBOL`, `/close all`, `/kill` require a follow-up `YES` reply within 90 seconds; any non-YES reply cancels the pending action; nonce and expiry are persisted across restarts
- **Commands**: `/status`, `/positions`, `/pnl`, `/trades [n]`, `/pause`, `/resume`, `/close SYMBOL`, `/close all`, `/kill`, `/config`

**19. Live balance sync**
- In `live` mode: fetches real USDT balance from exchange each cycle

**20. Daily session reset**
- At UTC midnight: resets the daily drawdown baseline to current balance; clears the daily drawdown pause flag

**21. Daily drawdown check**
- Computes `(current_balance - session_start_balance) / session_start_balance`
- If ≤ −5%: sets `daily_drawdown_paused = True`; no new entries for the rest of the UTC day

**22. Runtime position reconciliation** (live/shadow only)
- Fetches live exchange positions
- For each local open position not found on exchange: attempts to reconstruct close price from trade history; closes locally as `runtime_exchange_flat_reconciled`
- For each match with >1% quantity difference: updates local quantity/entry/side to exchange truth

---

### Position management (every cycle, all open positions)

**23. Price update per position**
- Fetches current market analysis for each open position
- Updates `current_price`, `gross_pnl`, `fee_cost` (0.11% round-trip on avg notional), `net_pnl`, `pnl_percentage`
- Tracks `peak_pnl_percentage` (high-water mark)
- Persists updated position to SQLite

**24. Hard stop-loss check**
- If `pnl_percentage ≤ −2.5%`: queued for close as `stop_loss`
- Checked immediately after every price refresh, before any other exit logic

**25. Partial profit taking**
- Three levels: 25% of remaining quantity at +2%, +3%, +5% gain
- Each level taken only once per position
- In live mode: submits a real reduce-only market order for the partial quantity
- PnL from partial exit added to balance and total PnL immediately
- Recorded in `partial_realizations` table
- If remaining quantity hits zero after a partial: closes as `partial_exit_complete`

**26. Trailing stop activation**
- Activates when `pnl_percentage ≥ 2%` and not yet active
- Sets initial trailing level at `peak_price × (1 − 1.5%)` for longs; `lowest_price × (1 + 1.5%)` for shorts
- In live mode: switches exchange-side protection from fixed SL/TP to native trailing stop order

**27. Trailing stop level update**
- On every cycle while active: recalculates level from `peak_pnl_percentage`; ratchets upward (long) or downward (short) only

**28. Trailing stop exit**
- If current price crosses the trailing stop level: queued for close as `TRAILING_STOP`

**29. Static stop-loss check**
- Checks `pos.stop_loss` field if set; closes as `SL_HIT` if breached

**30. Time-based exit**
- If position age ≥ 40 hours: queued for close as `time_exit`

**31. Position close execution**
- In live mode: submits a reduce-only market exit order; if rejected and exchange confirms no open position, treats as `native_sl_closed`; if genuine failure, re-queues for next cycle
- Cancels all native exchange stops on the symbol
- Cancels the companion limit order (if any) by id; treats `OrderNotFound` as success; cancel failures are non-blocking and emit a `companion_limit_cancel_failed` event
- Adds/subtracts net PnL to/from balance
- Consecutive loss counter: after 3 consecutive losses, enters an 8-hour cooldown blocking new entries
- Records closed trade to `closed_trades` table
- Emits structured event

---

### Entry scan (at 4H candle close only, or cycle 1 bootstrap)

**32. Entry gate evaluation**
- Checks three block conditions before scanning any symbol:
  - `manual_pause`: set by Telegram `/pause`
  - `daily_drawdown_pause`: −5% daily loss
  - `loss_cooldown`: post-3-consecutive-loss 8-hour block

**33. BTC regime filter**
- Fetches 260 × 4H candles for BTC/USDT
- Computes OHLC4, then a 90-period WMA
- If current BTC OHLC4 > WMA: only BUY signals allowed this window
- If current BTC OHLC4 ≤ WMA: only SELL signals allowed this window
- If fetch fails after 3 retries: skips the entire entry scan for this window

**34. Per-symbol entry analysis** (for each symbol in universe)

  a. **Ticker fetch & staleness check**
  - Fetches live ticker; extracts timestamp with multiple fallback fields
  - If ticker age > 600 seconds: skips symbol
  - Frozen ticker detection: if timestamp and price signature identical for ≥2 consecutive cycles: skips symbol

  b. **Volume filter**
  - 24h quote volume must exceed $5M
  - If volume data missing: skips symbol

  c. **OHLCV fetch**
  - Fetches last 100 × 4H candles; requires at least 47

  d. **OHLC4 calculation**
  - `(open + high + low + close) / 4` for each candle

  e. **WMA calculation**
  - 45-period Weighted Moving Average on OHLC4 series, with offset 2
  - Weights are linear 1→45
  - Returns `None` if insufficient data

  f. **Signal determination**
  - `BUY` if current OHLC4 > WMA; `SELL` otherwise

  g. **Signal confirmation**
  - Walks back through prior candles counting consecutive bars agreeing with signal direction
  - For BUY: requires prior candle close higher than highest close of those consecutive bars
  - For SELL: requires prior candle close lower than lowest close of those consecutive bars
  - Unconfirmed signals are skipped
  - Returns both the confirmation flag and the indices of the consecutive bars; the bar list is forwarded into the analysis result so downstream consumers (entry, companion limit) can reuse it without recomputing

  h. **ATR calculation**
  - 14-period Average True Range; if ATR/current price > 5%: entry size is halved

  i. **Regime alignment check**
  - Signal must match the BTC regime direction; misaligned signals skipped

  j. **Position cap check**
  - Max 10 open positions; stops scanning once cap reached

**35. Position open**
- Calculates gross notional: `balance × 11% × leverage`
- Deducts round-trip fee estimate (0.11%) to get net notional
- In live mode: submits market entry order; requires confirmed fill; refuses to open local position if fill unconfirmed
- Creates position object; persists to SQLite
- **Companion limit order placement** (immediately after the market position is persisted, before native protection is applied):
  - Selects the target bar from the consecutive-bars list returned by signal confirmation:
    - BUY: the bar with the highest close
    - SELL: the bar with the lowest close
  - Computes trigger price = `(target_bar.high + target_bar.low) / 2`
  - Side and quantity match the market entry exactly (same direction, same filled quantity)
  - In live mode: submits a limit order via the order executor with `order_reason='entry'`; stores the returned order id on the position; persists to SQLite; emits a `companion_limit_placed` structured event
  - In paper/shadow mode: logs the intended limit and emits a `companion_limit_logged` event; no exchange placement and no local resting-order simulation
  - Failure to place the limit is non-blocking — the market position is retained and a `companion_limit_skipped` event is emitted
  - The companion limit fills only on a pullback (BUY) or bounce (SELL); if it does fill, the extra exchange-side exposure is observed but not auto-merged into the local position model — startup and runtime reconciliation will surface any divergence
- Applies native exchange protection: sets fixed SL + TP order on exchange immediately after entry

---

### Funding rate tracking

**36. Funding PnL application**
- After position management loop each cycle: fetches latest funding rates for all open positions
- Applies cumulative funding costs/credits to balance and total PnL
- Persists funding payment records to SQLite
- Emits structured event if funding delta is non-zero

---

### Persistence & observability

**37. Runtime state persistence**
- After every significant action: writes balance, PnL, trade counts to `bot_state` SQLite table

**38. Structured event log** (`observability.jsonl`)
- Every significant event appended as a JSON line: timestamp, level, event type, run ID, component, symbol, values dict, human message

**39. Console + file logging**
- Dual-output: stdout and `usdt_trading_log.txt`
- Emoji filter applied to both handlers, strippable at runtime

**40. Display status**
- Printed every 6 cycles, whenever signals fire, or whenever positions are open
- Shows balance, total PnL, trade counts, and a table of all open positions
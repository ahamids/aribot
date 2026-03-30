# Live Bot Improvements — Project Spec
**Version**: 1.0  
**Repo**: live-trading-bot (Python, ccxt, SQLite, Bybit USDC perpetuals)  
**Orchestration**: Run autonomously via Agents Orchestrator

---

## Project Context

This is a live crypto trading bot for Bybit USDC perpetual swaps. It uses a WMA-45
signal on 4H candles with regime filtering, manages up to 6 concurrent positions, and
enforces tiered leverage, stop loss, partial profits, and trailing stops. The bot is
Python, uses ccxt for exchange access, and persists state in SQLite.

Three targeted improvements need to be implemented, tested on Bybit testnet, and
certified before merge to mainnet branch.

---

## Change 1 — PnL derivation: price-based, not margin-based

### Problem
Bybit calculates `unrealizedPnl%` as `unrealizedPnl / initialMargin`. At 3x leverage,
a 1% adverse price move appears as 3% on Bybit. The bot reads this field and uses it
to trigger stop loss at -2.5%, which fires at a real price move of only -0.83%.

This is most dangerous during reconciliation on restart: the bot reads the Bybit
position object, sees an inflated negative PnL%, and immediately triggers the stop loss
on positions that are well within the safe range.

### Required Fix
- NEVER read `percentage`, `unrealizedPnl%`, or any margin-relative PnL field from
  the Bybit position object.
- ALWAYS derive PnL% from price:
  - Long: `pnl_pct = (current_price - entry_price) / entry_price * 100`
  - Short: `pnl_pct = (entry_price - current_price) / entry_price * 100`
- Apply this to: position update loop, reconciler startup reconstruction, and any
  place `pnl_percentage` is written to SQLite.
- The `entry_price` used must be `avg_fill_price` (from the fill tracker), not the
  signal price.

### Files Affected
- `position_manager.py` — update price refresh method
- `reconciler.py` — update startup position reconstruction
- `live_bot.py` — any inline PnL reads
- `test_live_bot.py` — add tests for both long and short PnL derivation,
  and a reconciliation test that confirms no false stop triggers

---

## Change 2 — Native Bybit stop loss, trailing stop, and take profit

### Problem
All stop management currently runs in the bot's internal loop. If the bot crashes or
is killed mid-session, open positions have no protection on the exchange side. A gap
move while the bot is offline will not trigger any stop.

### Required Fix
Use Bybit's `set_trading_stop` endpoint (via ccxt) to set exchange-native orders:

**On position open:**
- Set native stop loss at the same price the internal stop is calculated at.
  Stop price formula:
  - Long: `entry_price * (1 - 0.025)` (i.e. -2.5%)
  - Short: `entry_price * (1 + 0.025)`
- Trigger type: `MarkPrice` (prevents wick-only fills on low-liquidity alts)
- ccxt call: `exchange.set_trading_stop(symbol, params={'stopLoss': price, 'slTriggerBy': 'MarkPrice', 'positionIdx': 0})`

**Trailing stop (when internal trailing activates at +2%):**
- Set native trailing stop via `trailingStop` callback rate.
- The bot's buffer is 1.5% from peak, so callback rate = `0.015`.
- ccxt call: `exchange.set_trading_stop(symbol, params={'trailingStop': '0.015'})`
- When native trailing is set, also cancel the native fixed stop loss (it is now
  superseded).

**Take profit (partial exits at 2%, 3%, 5%):**
- Bybit's TP closes the entire position — do NOT use it for partial exits.
- The partial exit logic remains internal (market orders placed by the bot).
- Set native TP only for the final full exit at +5% as a safety net:
  - Long: `entry_price * 1.05`
  - Short: `entry_price * 0.95`
  - Clear this TP when the position reaches the trailing stop stage (trail supersedes).

**On position close (any reason):**
- Cancel all native SL/TP/trail orders: call `set_trading_stop` with empty values
  to clear residual orders after internal close.

**Error handling:**
- If `set_trading_stop` fails, LOG WARNING but do NOT block position opening.
  The internal loop remains the primary mechanism; native orders are a safety net.
- Store whether native SL/TP are active in the positions table (boolean columns).

### New SQLite Columns (positions table)
- `native_sl_active BOOLEAN DEFAULT 0`
- `native_tp_active BOOLEAN DEFAULT 0`
- `native_trail_active BOOLEAN DEFAULT 0`
- `native_sl_price REAL`

### Files Affected
- `order_executor.py` — add `set_native_stops(symbol, entry_price, side)` method
- `position_manager.py` — call set_native_stops on open; update/cancel on close
- `reconciler.py` — on startup, re-set native stops for positions that have none
- `db_schema.py` — add new columns
- `migrate_v2_to_live.sql` — ALTER TABLE for new columns
- `test_live_bot.py` — testnet round-trip: open position, verify SL appears on Bybit,
  close position, verify SL is cleared

**Important constraint**: Bybit's native trailing stop uses a callback rate from the
activation moment, not from an externally tracked peak. The internal trailing stop
logic (tracking peak_pnl_percentage and deriving trail level) remains the PRIMARY
exit mechanism. The native trailingStop is a FALLBACK only. Do not remove internal
trailing stop logic.

---

## Change 3 — Explicit leverage setting before order placement

### Problem
The bot calculates tiered leverage per symbol (BTC/ETH=5x, SOL/BNB/DOT/AVAX=3x,
mid-caps=2x, others=1x from leverage_buckets.json) but never explicitly sets leverage
on Bybit before placing orders. If the exchange account has a cached different leverage
for that symbol, orders execute at the wrong size.

### Required Fix
Before every market order, call `set_leverage` on Bybit:
```python
exchange.set_leverage(
    leverage,
    symbol,
    params={'buyLeverage': leverage, 'sellLeverage': leverage}
)
```

- This call is idempotent — Bybit accepts it with success even if leverage is already
  correct.
- Must happen in `order_executor.py` BEFORE the market order call, inside the same
  method that places the entry.
- If `set_leverage` raises an exception, LOG ERROR and abort the order — do not
  proceed with potentially wrong leverage.
- After set_leverage, log the confirmed leverage value.
- For Bybit USDC perps, both `buyLeverage` and `sellLeverage` must be set explicitly.

### Files Affected
- `order_executor.py` — add `_ensure_leverage(symbol, leverage)` private method;
  call it at the start of `place_market_order`
- `test_live_bot.py` — testnet test: open position on BTCUSDT at 5x, confirm Bybit
  position shows leverage=5; open on a mid-cap at 2x, confirm leverage=2

---

## Acceptance Criteria (all three changes must pass before merge)

1. A testnet run with at least 2 positions opened confirms:
   - PnL% shown in bot logs matches (current_price - entry_price) / entry_price,
     NOT Bybit's margin-based percentage.
   - On restart mid-position, reconciler does not trigger false stop losses.
   - Bybit position page shows correct SL price immediately after open.
   - Bybit position page shows trailing stop active when internal trail activates.
   - Bybit position page shows correct leverage (matching leverage_buckets.json).

2. Reality Checker must certify PASS on:
   - No Bybit PnL fields read anywhere in codebase (grep check)
   - set_leverage called before every market order (code review)
   - set_trading_stop error does not crash the bot (exception handling review)
   - All new SQLite columns added with migration script (schema review)
   - Test coverage: at least 1 test per acceptance criterion above

---

## Orchestration Instructions

Pipeline:
`agents-orchestrator → project-manager-senior → [backend-architect × 3 branches] →
[senior-developer + copilot-inline × 3] → [api-tester × 3] → reality-checker`

Branch parallelism: Changes 1 and 3 can be developed in parallel (no shared files).
Change 2 depends on Change 1 being complete first (it reads the corrected PnL to
decide when to activate trailing stop natively).

Dependency order:
1. Change 3 (leverage setter) — independent, simplest, do first
2. Change 1 (PnL fix) — independent, must complete before Change 2
3. Change 2 (native stops) — depends on Change 1

Each change gets its own feature branch. Merge order: change-3 → change-1 → change-2.
```

---

## The Orchestrator activation prompt

Copy this verbatim into Copilot Chat after installing the agents:
```
Use the Agents Orchestrator agent.

Execute the complete development pipeline for the spec at
project-specs/live-bot-improvements.md

Run this autonomous workflow:
1. project-manager-senior: Decompose the spec into atomic tasks with explicit
   dependency ordering. Produce a numbered task list with acceptance criteria per task.

2. backend-architect (× 3 parallel branches, one per change):
   - Branch A: PnL derivation module — design the price-based PnL calculation,
     the reconciler fix, and all affected interfaces.
   - Branch B: Native stop/TP/trail layer — design the set_trading_stop integration,
     error handling, and SQLite schema additions.
   - Branch C: Leverage setter — design the _ensure_leverage method and the abort
     logic on failure.

3. senior-developer + copilot-inline (× 3, following dependency order C → A → B):
   For each branch: implement the design, write inline comments as Copilot prompts
   where complex logic needs generation, and produce a diff summary per file changed.

4. api-tester (× 3): Write testnet validation tests for each branch. Each test must
   produce a PASS/FAIL result against Bybit testnet with real API calls.

5. reality-checker: Certify all three branches meet acceptance criteria. Provide
   a signed-off PASS or a list of required fixes before merge is allowed.

Context files to load:
- README.md (current live bot spec)
- specs/live-bot-improvements.md (this spec)
- order_executor.py, position_manager.py, reconciler.py (existing code)

Do not advance to the next agent until the current agent's deliverable is complete.
```

---

## Per-agent prompts for manual Copilot use

If you prefer to drive each agent individually rather than through the Orchestrator, here are the exact prompts. They match what the Orchestrator would dispatch.

**Senior Project Manager — task breakdown:**
```
Use the Senior Project Manager agent. The project spec is in
project-specs/live-bot-improvements.md. Produce a numbered task list where each task:
has a single acceptance criterion, can be completed in under 2 hours, names the file
it touches, and lists any task numbers it depends on. Group by: Change 3 (leverage),
Change 1 (PnL), Change 2 (native stops) in that order.
```

**Backend Architect — Change 1 (PnL):**
```
Use the Backend Architect agent. Design the PnL derivation fix for a live Bybit USDC
perpetuals bot. Currently the bot reads `percentage` from the Bybit position object
(margin-based). Requirement: derive PnL% as price-based only.

Produce:
1. The `derive_pnl_pct(entry_price, current_price, side)` function signature and logic
2. A list of every callsite in position_manager.py and reconciler.py that must be
   updated, with the exact field name being replaced
3. The unit test cases (entry=100, current=97.5, side=long → expected -2.5%; same
   for short)
4. The reconciliation test: position in SQLite at entry=100, Bybit reports current=97,
   confirm bot shows -3.0%, confirm stop does NOT trigger at -3.0% (threshold is -2.5%)
```

**Backend Architect — Change 2 (native stops):**
```
Use the Backend Architect agent. Design the native Bybit stop management layer.

Requirements from spec: set_trading_stop on open (SL at -2.5%), set trailingStop
callback=0.015 when internal trail activates, set TP at +5% as final safety, cancel
all on close. Errors must not block order placement.

Produce:
1. The complete `NativeStopManager` class interface with method signatures
2. The exact ccxt call parameters for each operation (stopLoss, trailingStop, takeProfit,
   positionIdx, slTriggerBy) for Bybit USDC perpetuals
3. The SQLite migration: 4 new columns on positions table
4. The error handling decision tree: what to do if set_trading_stop times out, returns
   partial failure, or returns "position not found"
5. The sequence diagram: open position → set SL → partial exit → trail activates →
   set trail + cancel SL → position closes → cancel all native orders
```

**Backend Architect — Change 3 (leverage):**
```
Use the Backend Architect agent. Design the leverage-setting pre-check for a live Bybit
bot. Before every market order, `set_leverage` must be called and confirmed.

Produce:
1. The `_ensure_leverage(symbol, leverage)` private method in OrderExecutor
2. The exact ccxt call: exchange.set_leverage with both buyLeverage and sellLeverage
   params for Bybit USDC perps
3. The abort logic: if set_leverage raises, log ERROR with symbol+leverage, raise
   LeverageSetError, do not place order
4. The happy-path log line format: "Leverage confirmed: {symbol} = {leverage}x"
5. The test: call place_market_order for BTCUSDT with leverage=5, assert set_leverage
   was called with correct params before create_order
```

**API Tester — all three changes combined:**
```
Use the API Tester agent. Write testnet validation tests in test_live_bot.py for all
three changes.

Test 1 (Change 1 — PnL): Open a long position on Bybit testnet. Read the position
back. Assert that bot's pnl_pct equals (current_price - entry_price)/entry_price*100,
not the exchange's percentage field. Inject a simulated restart: reload position from
SQLite, call reconciler, assert no stop-loss trigger fires on a position that is
only -1% in price.

Test 2 (Change 2 — native stops): Open a position on testnet. Immediately fetch
the position from Bybit and confirm stopLoss is set at entry * 0.975 for a long.
Wait for internal trailing to activate (mock peak_pnl to +2%). Confirm Bybit shows
trailingStop = '0.015'. Close position internally. Confirm Bybit position shows no
active SL or TP.

Test 3 (Change 3 — leverage): Open a position on SOLUSDT testnet with leverage=3.
Fetch position from Bybit, assert leverage field equals 3. Open a second position on
BTCUSDT with leverage=5. Assert leverage=5. Assert set_leverage was called before
each create_order call.

Each test: print PASS with timestamp or FAIL with exact assertion message and
exchange response. All three must PASS before merge.
```

**Reality Checker — final certification:**
```
Use the Reality Checker agent. Certify these three changes for production readiness.

Evidence required for PASS on each item:

CHANGE 1 — PnL derivation:
[ ] grep result: zero occurrences of 'percentage', 'unrealizedPnl', or 'info' dict
    reads for PnL in position_manager.py and reconciler.py
[ ] Test 1 from test_live_bot.py passes on testnet
[ ] Code shows derive_pnl_pct called at every position update point

CHANGE 2 — Native stops:
[ ] set_trading_stop exception is caught and logged — does NOT propagate
[ ] Test 2 from test_live_bot.py passes: SL present after open, cleared after close
[ ] Migration script tested: all 4 new columns present in positions table
[ ] No place in code assumes native stops are set — internal loop still primary

CHANGE 3 — Leverage:
[ ] _ensure_leverage called before EVERY create_order call — no bypasses
[ ] LeverageSetError aborts order correctly — no order placed on failure
[ ] Test 3 from test_live_bot.py passes on testnet
[ ] Both buyLeverage and sellLeverage params present in set_leverage call

Certify PASS or list exactly what is missing with the file and line number.
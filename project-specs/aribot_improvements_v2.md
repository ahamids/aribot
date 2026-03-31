# Aribot improvements — v2 spec
**For**: Agents Orchestrator autonomous pipeline  
**Repo**: aribot (Python, ccxt, SQLite, Bybit USDT perpetuals, Telegram dispatcher)  
**Dependency order**: Issue 1 is independent. Issues 2, 3, 4 are independent of each other
and of Issue 1. All four can be worked in parallel.

---

## Issue 1 — Residual exchange orders opening counter positions after close

### Observed behaviour
After the bot internally closes a position (via stop loss, trailing stop, time exit,
or partial exit completing to zero), a counter position is subsequently found open on
Bybit. The suspected root cause is that one or more native trading-stop orders
(stopLoss, takeProfit, or trailingStop set via `set_trading_stop`) remain active on
the exchange after the bot's internal close action executes. When these residual orders
later trigger, Bybit treats them as new entry signals in the opposite direction,
opening a counter position the bot has no record of.

### Investigation required
Before implementing a fix, the assigned agent must:

1. Audit every position close path in the codebase and confirm whether
   `cancel_native_stops(symbol)` is called on each path. Close paths include:
   - Hard stop loss trigger (`pnl% <= -2.5`)
   - Trailing stop breach
   - Time exit (40-hour limit)
   - Partial exit sequence completing to zero quantity
   - Manual `/close SYMBOL` Telegram command
   - Kill switch emergency close-all flow
   - Reconciler-initiated close (ghost position or drift correction)

2. Confirm the exact ccxt call used to cancel all active trading-stop orders on Bybit
   USDT perpetuals. The correct approach is to call `set_trading_stop` with explicit
   zeroed/empty values for `stopLoss`, `takeProfit`, and `trailingStop` simultaneously,
   not sequentially. Verify this clears all three in one call and does not leave
   residual orders.

3. Determine whether Bybit's order type for trading-stop orders is `reduce-only`.
   If it is not set as reduce-only, confirm whether this is the mechanism by which
   a triggered residual order opens a new position rather than simply closing.
   If reduce-only is not being set, this must be corrected at the point of
   `set_trading_stop` creation as well as at cancellation.

### Required fix

1. Create or confirm a `cancel_all_native_stops(symbol)` method in
   `order_executor.py` that issues a single `set_trading_stop` call clearing
   `stopLoss`, `takeProfit`, and `trailingStop` in one request. This method must:
   - Be non-blocking on failure (log WARNING, do not raise)
   - Log the result: confirmed cancelled or failed with reason
   - Be idempotent: calling it when no native stops exist must not error

2. Audit every close path listed above and add a `cancel_all_native_stops(symbol)`
   call immediately after the close order is confirmed filled. It must execute after
   fill confirmation, not before — cancelling before fill could leave the position
   unprotected if the close order is rejected.

3. If the investigation confirms that `reduce-only` was not set on the original
   trading-stop orders, add `reduceOnly: true` to all `set_trading_stop` calls
   in `order_executor.py`. This is a belt-and-suspenders fix: even if the cancel
   call fails, a reduce-only residual order cannot open a new position.

4. Update `positions` table: add a `native_stops_cancelled_at` TIMESTAMP column.
   Write the timestamp when `cancel_all_native_stops` succeeds for a position.
   This allows post-hoc audit of whether the cancel ran before or after the
   counter position appeared.

### Files affected
- `order_executor.py` — `cancel_all_native_stops` method; `reduce_only` flag on
  all `set_trading_stop` calls
- `position_manager.py` — all close paths must call `cancel_all_native_stops`
- `reconciler.py` — close paths must call `cancel_all_native_stops`
- `kill_switch_monitor.py` — emergency close-all must call `cancel_all_native_stops`
  per symbol before or after each close order
- `db_schema.py` — add `native_stops_cancelled_at` column
- `migrate_v2_to_live.sql` — ALTER TABLE positions ADD COLUMN

### Acceptance criteria
- Code review confirms `cancel_all_native_stops` is present on every close path
  with no exceptions
- Testnet test: open a position, set native SL and TP, close the position via
  the bot's internal stop logic, then immediately fetch open orders from Bybit —
  zero native orders should remain
- Testnet test: trigger the kill switch with two open positions — confirm both
  positions close and all native orders are cleared within 60 seconds
- If `reduce-only` was missing: confirm it is now set on all new `set_trading_stop`
  calls via testnet order inspection

---

## Issue 2 — Telegram /status: add balance and win/loss counts

### Current behaviour
`/status` returns: mode, regime direction, session PnL, loop cycle count,
drawdown %, cooldown state.

### Required change
Add the following fields to the `/status` reply:

1. **Current balance** — read from `bot_state` table or the in-memory balance
   tracker, formatted to 2 decimal places with currency symbol.
   Example: `Balance: $10,432.18`

2. **Win / loss count** — total wins and losses for the current session
   (since process start), sourced from the in-memory counters already tracked
   for the consecutive-loss cooldown logic.
   Example: `Wins: 8  Losses: 5`

### Format requirement
The two new fields must appear as their own lines in the reply, positioned after
session PnL and before drawdown status. The overall message must remain readable
on a mobile Telegram screen — no tables, no markdown that Telegram does not render.

### Files affected
- `alert_dispatcher.py` (or wherever Telegram command handlers live) — update
  `/status` handler to include balance and win/loss fields

### Acceptance criteria
- Send `/status` to the bot; reply contains `Balance:` and `Wins: / Losses:` lines
- Balance value matches the value logged in the most recent bot loop cycle
- Win/loss counts match the values in `bot_state` or the in-memory session counters

---

## Issue 3 — Telegram /positions: show open position count in header

### Current behaviour
`/positions` reply begins with the header text `Positions` followed by the list.

### Required change
Change the header to `Positions (n)` where `n` is the count of currently open
positions. `n` must be derived from the live positions query, not a cached value.

If there are zero open positions, the reply should read:
`Positions (0) — none open`
rather than an empty list, to make it unambiguous that the command executed
successfully.

### Files affected
- `alert_dispatcher.py` (or wherever `/positions` handler lives) — update header
  construction

### Acceptance criteria
- `/positions` with 3 open positions returns `Positions (3)` as the header
- `/positions` with no open positions returns `Positions (0) — none open`
- Count matches the actual number of rows in the `positions` table at query time

---

## Issue 4 — Hourly automated pulse message via Telegram

### Required behaviour
The bot must send an automated Telegram message once every 60 minutes while
running. This serves as a heartbeat: if the message stops arriving, the operator
knows the process has died or the VPS has lost connectivity.

### Message content
The pulse message must include:
- Label identifying it as a scheduled pulse (not a trade alert)
- Current time (UTC)
- Bot mode (paper / shadow / live)
- Number of open positions
- Current balance
- Session PnL (realised)
- Whether entries are currently paused (drawdown breaker or cooldown active)

Example format:
```
[Pulse 14:00 UTC]
Mode: live | Positions: 4 | Balance: $10,432.18
Session PnL: +$87.42 | Entries: active
```

### Implementation requirements

1. The 60-minute interval must be tracked inside the main bot loop using elapsed
   time since last pulse, not a separate thread or scheduler. The bot's loop runs
   every 60 seconds; the pulse check is a simple elapsed-time comparison at the
   top of each cycle.

2. The first pulse must be sent at bot startup (after reconciliation and
   Telegram verify check complete), so the operator immediately knows the bot
   is live. Subsequent pulses send at 60-minute intervals from that first send.

3. If the Telegram send fails, log WARNING and continue — the pulse must never
   block or crash the main loop. Record the failure in `observability.jsonl`.

4. The pulse must use the existing `AlertDispatcher` send path, not a new
   HTTP call, to benefit from the existing retry and error-handling logic.

5. Persist `last_pulse_sent_at` in the `bot_state` table so that on restart
   the bot does not immediately send a duplicate pulse if it restarted within
   the 60-minute window.

### Files affected
- `usdt_paper_bot_v2.py` (main loop) — add elapsed-time pulse check
- `alert_dispatcher.py` — add `send_pulse(status_data)` method
- `db_schema.py` — add `last_pulse_sent_at` column to `bot_state`
- `migrate_v2_to_live.sql` — ALTER TABLE bot_state ADD COLUMN

### Acceptance criteria
- On fresh start, a pulse message arrives in Telegram within 30 seconds of
  the main loop beginning
- A second pulse arrives 60 minutes (±2 minutes) later
- Kill the process and restart; confirm that if less than 60 minutes has elapsed
  since the last pulse (read from `bot_state`), the bot waits for the remaining
  interval before sending the next pulse rather than sending immediately
- A Telegram send failure during pulse does not stop the bot loop; the failure
  appears in `observability.jsonl`

---

## Orchestration instructions

Pipeline:
`agents-orchestrator → project-manager-senior → [backend-architect per issue] →
[senior-developer + copilot-inline per issue] → [api-tester per issue] →
reality-checker`

Parallelism: All four issues are independent and can be developed simultaneously
on separate feature branches.

Merge order: No dependencies between issues. Merge in any order after
individual reality-checker sign-off. Run full testnet smoke test after all
four are merged to confirm no regressions across the integrated system.

Branch naming:
- `feature/fix-counter-positions`
- `feature/telegram-status-balance`
- `feature/telegram-positions-count`
- `feature/telegram-hourly-pulse`
# Branch B Architecture: Native Stop/TP/Trailing Integration

## Scope
This design covers only Branch B for native exchange-protection controls via Bybit `set_trading_stop`.

In scope:
- Native SL on position open
- Native trailing callback activation at internal trailing stage
- Native final TP (+5%) as safety net only
- Non-blocking error handling for native-stop API failures
- SQLite schema additions and migration
- Startup reconciler behavior for missing native protection

Out of scope:
- PnL derivation rewrite (Branch A)
- Leverage pre-check (Branch C)

## Repo Mapping (spec -> this repo)
- position_manager/live_bot -> `aribot/runtime/engine.py`
- reconciler -> `startup_reconciler.py`
- db schema owner -> `aribot/runtime/engine.py` (`setup_database`)
- migration entrypoint -> `migrate_live_schema.py`
- execution wrapper for exchange calls -> `order_executor.py`

## Design Goals
- Exchange-native protection exists even if bot process dies.
- Internal exit logic remains primary; native controls are fallback only.
- Native-stop API failures never block opening or managing a position.
- Native state is persisted in SQLite for observability and reconciliation repair.

## Native Stop Manager Placement
Use `OrderExecutor` as the exchange adapter layer for `set_trading_stop` so `Aribot` stays orchestration-focused.

Planned API in `order_executor.py`:
- `set_native_initial_protection(symbol: str, side: str, entry_price: float) -> dict`
- `set_native_trailing(symbol: str) -> dict`
- `clear_native_protection(symbol: str) -> dict`
- `ensure_native_protection_for_position(symbol: str, side: str, entry_price: float, trailing_active: bool) -> dict`

Each method returns structured status, for example:
- `{ "ok": true, "operation": "set_initial", "warnings": [] }`
- `{ "ok": false, "operation": "set_trailing", "error_type": "ExchangeTimeout", "error": "..." }`

No method raises by default for native-stop failures; they log warning and return non-ok status.

## Exact Bybit set_trading_stop Parameters

### 1) Initial native SL on open (MarkPrice)
Trigger point:
- Immediately after a successful entry fill in `aribot/runtime/engine.py` when `PaperPosition` is created and persisted.

Price formula:
- Long SL: `entry_price * (1 - 0.025)`
- Short SL: `entry_price * (1 + 0.025)`

Call:
```python
exchange.set_trading_stop(
    symbol,
    params={
        "stopLoss": str(sl_price),
        "slTriggerBy": "MarkPrice",
        "positionIdx": 0,
    },
)
```

DB flags after success:
- `native_sl_active = 1`
- `native_sl_price = sl_price`
- `native_tp_active = 0` initially until TP is explicitly set
- `native_trail_active = 0`

### 2) Native final TP safety net (+5%)
Behavior:
- Native TP is never used for partials.
- It is set as full-position fallback only.

Price formula:
- Long TP: `entry_price * 1.05`
- Short TP: `entry_price * 0.95`

Call (paired with initial protection stage):
```python
exchange.set_trading_stop(
    symbol,
    params={
        "takeProfit": str(tp_price),
        "positionIdx": 0,
    },
)
```

DB flags after success:
- `native_tp_active = 1`

### 3) Native trailing activation (callback = 0.015)
Trigger point:
- In `aribot/runtime/engine.py` inside `update_positions`, exactly when internal trailing transitions to active (`pos.should_activate_trailing_stop()` branch).

Call:
```python
exchange.set_trading_stop(
    symbol,
    params={
        "trailingStop": "0.015",
        "positionIdx": 0,
    },
)
```

At same transition, clear fixed native SL and fixed TP (trail supersedes fixed protection):
```python
exchange.set_trading_stop(
    symbol,
    params={
        "stopLoss": "0",
        "takeProfit": "0",
        "positionIdx": 0,
    },
)
```

DB flags after successful trailing stage:
- `native_trail_active = 1`
- `native_sl_active = 0`
- `native_tp_active = 0`
- `native_sl_price = NULL`

### 4) Clear residual native orders on close
Trigger point:
- In `aribot/runtime/engine.py` within `close_position`, after exit order is confirmed (or during any local forced close path), before local row deletion.

Primary clear call:
```python
exchange.set_trading_stop(
    symbol,
    params={
        "stopLoss": "0",
        "takeProfit": "0",
        "trailingStop": "0",
        "positionIdx": 0,
    },
)
```

Fallback clear call if required by exchange adapter behavior:
```python
exchange.set_trading_stop(
    symbol,
    params={
        "stopLoss": None,
        "takeProfit": None,
        "trailingStop": None,
        "positionIdx": 0,
    },
)
```

Then force DB flags to off before removing persisted position:
- `native_sl_active = 0`
- `native_tp_active = 0`
- `native_trail_active = 0`
- `native_sl_price = NULL`

## aribot/runtime/engine.py Integration Points

### Position open flow
Current location: entry path that creates `PaperPosition` and calls `persist_position(pos)`.

Add step order:
1. Create position from fill price (`avg_fill_price` path already present).
2. Persist position row.
3. If live execution enabled, call `order_executor.set_native_initial_protection(...)`.
4. If call succeeds, update native columns in `positions`.
5. If call fails, log warning and continue (non-blocking).

### update_positions trailing transition
Current location: block under `if pos.should_activate_trailing_stop():`.

Add:
1. Keep existing internal trail activation unchanged.
2. Call `order_executor.set_native_trailing(symbol)`.
3. On success, mark native flags trail-only in DB.
4. On failure, warn and continue; internal trailing remains primary.

### close_position flow
Current location: `close_position(self, symbol, reason)`.

Add:
1. Attempt `order_executor.clear_native_protection(symbol)` before deleting row.
2. Never block close if clearing fails; warn and continue.
3. Force native flag columns to 0/NULL before deletion to keep local accounting consistent in failure windows.

## startup_reconciler.py Integration
Goal: on startup, if a local open position lacks native protection, try to restore it.

Add a post-reconciliation protection pass (only when report passes startup gate):
1. For each local/exchange-overlap open position, read local native flags.
2. If all false (`native_sl_active = 0`, `native_tp_active = 0`, `native_trail_active = 0`), re-apply:
- SL + final TP if local trailing inactive
- trailing callback if local trailing active
3. On success, persist flags.
4. On failure, warning only; do not fail startup gate.

This preserves existing startup safety rule: ghost positions remain blocking/critical; missing native protection is repairable and non-blocking.

## SQLite Schema Additions

### positions table columns (required)
Add to `aribot/runtime/engine.py` `setup_database` for fresh DBs:
- `native_sl_active INTEGER DEFAULT 0`
- `native_tp_active INTEGER DEFAULT 0`
- `native_trail_active INTEGER DEFAULT 0`
- `native_sl_price REAL`

Boolean representation:
- Store booleans as SQLite INTEGER (`0` or `1`) for compatibility with existing schema style.

### migrate_live_schema.py for existing DBs
Extend `POSITIONS_ADDITIONAL_COLUMNS`:
- `"native_sl_active": "INTEGER DEFAULT 0"`
- `"native_tp_active": "INTEGER DEFAULT 0"`
- `"native_trail_active": "INTEGER DEFAULT 0"`
- `"native_sl_price": "REAL"`

Migration behavior remains idempotent via `PRAGMA table_info` checks.

## Error Handling Decision Tree (Non-Blocking)

### set_trading_stop timeout/network errors
- Log `WARNING` with symbol, operation, payload summary, exception type.
- Return `{ok: false, error_type: "timeout_or_network"}`.
- Continue bot flow; internal stop logic remains active.

### Exchange returns partial failure / validation error
- Log `WARNING` with returned error code/message.
- Mark only confirmed local flags as active; do not assume success.
- Continue bot flow.

### Exchange returns "position not found"
- For open path: warning and continue (can happen during fill-state propagation race).
- For close path clear: info/warning and continue (position may already be closed).
- For reconciler restore: warning and continue.

### Logging contract
Use structured context in each warning:
- `symbol`
- `operation` (`set_initial`, `set_tp`, `set_trailing`, `clear_all`)
- `position_side`
- `entry_price` when available
- `native_payload`
- `error_type`

## Lifecycle Sequence (Branch B)
1. Open position confirmed.
2. Set native SL (MarkPrice) and native final TP (+5%).
3. Internal partial exits continue as today (no native TP for partial legs).
4. Internal trailing activates at +2%.
5. Set native trailing callback `0.015`; clear native fixed SL and TP.
6. Position closes by any internal reason.
7. Clear all native residual orders via `set_trading_stop` zero/empty payload.
8. Remove local position row.

## Data Contract for Position State
For in-memory `PaperPosition` no new fields are required for decisioning.
Native protection state should be persisted in DB and only loaded when needed for:
- startup restore decisions
- observability/reporting

If loaded into memory later, use these semantic meanings:
- `native_sl_active`: exchange fixed SL currently expected active
- `native_tp_active`: exchange final TP fallback currently expected active
- `native_trail_active`: exchange trailing callback currently expected active
- `native_sl_price`: last configured native SL price (nullable)

## Acceptance Checks for Branch B Design
- Open flow does not abort if `set_trading_stop` fails.
- Native SL request always uses `slTriggerBy = MarkPrice` and `positionIdx = 0`.
- Trailing activation sends `trailingStop = "0.015"`.
- Final TP is only full-position +5% fallback, not used for partial exits.
- Close flow attempts clear-all native stops and never blocks closure.
- Schema/migration contain all four native columns exactly:
- `native_sl_active`
- `native_tp_active`
- `native_trail_active`
- `native_sl_price`

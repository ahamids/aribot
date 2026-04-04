# Branch A Architecture - Price-Based PnL Derivation

## Scope

This design covers only **Change 1** from `specs/live_bot_improvements.md`:
- Derive `pnl_percentage` from price only.
- Do not consume margin-relative PnL fields from Bybit position payloads.
- Ensure startup reconciliation and SQLite persistence use the same price-based PnL contract.

Repository mapping for this branch:
- Position manager/live bot: `aribot/runtime/engine.py`
- Reconciler: `startup_reconciler.py`

## Problem Statement

Bybit margin-relative percentage (for example `unrealizedPnl / initialMargin`) is leverage-amplified and not suitable for strategy-level risk triggers. If consumed, stop-loss logic can trigger too early, especially after restart and reconciliation.

Branch A enforces a single invariant:

> `pnl_percentage` is always derived from `(entry_price, current_price, side)` and never from exchange-provided percentage fields.

## Canonical PnL Function

Add a shared pure function:

```python
def derive_pnl_pct(entry_price: float, current_price: float, side: str) -> float:
    """Return price-based PnL percent, strategy-facing, independent of leverage."""
    try:
        ep = float(entry_price)
        cp = float(current_price)
    except (TypeError, ValueError):
        return 0.0

    if ep <= 0.0:
        return 0.0

    normalized_side = str(side or "").strip().lower()
    if normalized_side in {"long", "buy"}:
        return ((cp - ep) / ep) * 100.0
    if normalized_side in {"short", "sell"}:
        return ((ep - cp) / ep) * 100.0

    # Fail-safe: unknown side is treated as flat risk signal.
    return 0.0
```

Required behavior checks:
- `entry=100, current=97.5, side=long` -> `-2.5`
- `entry=100, current=97.5, side=short` -> `+2.5`
- `entry=100, current=103, side=long` -> `+3.0`
- `entry=100, current=103, side=short` -> `-3.0`

## Entry Price Source Contract (Live Orders)

For live execution, `entry_price` must come from order fill aggregation (`avg_fill_price`), not signal price.

Current flow already supports this and must be preserved as a hard requirement:
1. `OrderExecutor._build_fill_summary` returns `avg_fill_price` from matched fills.
2. `Aribot.extract_order_fill` prefers `avg_fill_price` over `average` and `price`.
3. `Aribot.open_position` overwrites fallback analysis price with `extract_order_fill(...)` output.
4. `PaperPosition` is created using this fill-derived price and persisted to `positions.entry_price`.

Design guardrail:
- In live mode, `entry_price` assignment in open path must be the resolved `avg_fill_price` chain result.
- Signal/analysis price is only a temporary fallback before fill data is available.

## Where to Apply `derive_pnl_pct`

## 1) Position Price Refresh Loop (`aribot/runtime/engine.py`)

Primary loop:
- `Aribot.update_positions` calls `pos.update_price(analysis['current_price'])`.
- `pnl_percentage` drives:
  - `should_close_for_loss()`
  - trailing activation/update
  - partial profit triggers
  - persisted values/logs/events

Architecture change:
- Inside `PaperPosition.update_price`, compute:
  - `self.pnl_percentage = derive_pnl_pct(self.entry_price, self.current_price, self.side)`
- Keep `self.pnl` (net currency PnL) as-is for balance accounting.
- Decouple percentage from fee-based notional normalization, so stop logic is tied only to market movement.

Rationale:
- Risk threshold `-2.5%` represents true adverse price move regardless of leverage.

## 2) Startup Recovery of Persisted Positions (`aribot/runtime/engine.py`)

Current startup path:
- `load_state()` hydrates rows from `positions`.
- `reconcile_positions_on_startup()` fetches fresh market price and runs `pos.update_price(...)` before close checks.

Architecture implication:
- As long as `update_price` uses `derive_pnl_pct`, recovery stop decisions are protected from margin-relative distortion.
- Any stale DB `pnl_percentage` is recomputed on first startup tick, then overwritten by `persist_position`.

## 3) Startup Reconciler Exchange-Truth Upsert (`startup_reconciler.py`)

Current reconciler behavior:
- `upsert_local_position_from_exchange(...)` writes exchange `entry_price`, sets `current_price=entry_price`, `pnl=0`, `pnl_percentage=0`.

Required behavior for Branch A:
- Continue writing `pnl_percentage=0` on upsert bootstrap.
- Never source `pnl_percentage` from exchange payload.
- Let the live bot startup refresh (`reconcile_positions_on_startup`) immediately compute price-based `pnl_percentage` from current market via `derive_pnl_pct`.

Optional improvement (same branch, low risk):
- If a trusted current price snapshot is available during reconciler upsert, compute initial `pnl_percentage` with `derive_pnl_pct`; otherwise keep zero and rely on first loop refresh.

## 4) Closed Trade Archival in Reconciler (`startup_reconciler.py`)

Current `archive_local_position_as_closed(...)` path already computes:
- cash PnL from entry/close and side
- `pnl_pct = pnl / (entry_price * qty) * 100`

This is mathematically equivalent to price-based percent when `qty` cancels. To unify logic and avoid divergence, call `derive_pnl_pct(entry_price, close_price, side)` for `pnl_pct`.

## SQLite Write Implications

No schema migration is required for Branch A. Behavior-level implications:

1. `positions.pnl_percentage`
- Written by `persist_position`.
- Must always represent `derive_pnl_pct(entry_price, current_price, side)`.
- Treated as cached/derived value, not source of truth.

2. `closed_trades.pnl_percentage`
- Written by both:
  - `Aribot.record_closed_trade`
  - `StartupReconciler.archive_local_position_as_closed`
- Must be price-based and side-aware using the same function to avoid drift between normal close and reconstructed close.

3. Restart consistency
- `load_state` can load historical `pnl_percentage`, but first price refresh recomputes and overwrites.
- This preserves forward correctness without needing a backfill migration.

## Field Ban List (Bybit)

Branch A enforces a strict denylist for strategy PnL percentage:
- `percentage`
- `unrealizedPnl%`
- any `unrealizedPnl / initialMargin` derived field
- any exchange-specific margin-relative PnL percent

Accepted exchange fields:
- `entryPrice` (for position reconstruction only)
- fills/trades used to compute `avg_fill_price`
- raw mark/last/current price needed for `current_price`

## Integration Points Summary

In `aribot/runtime/engine.py`:
- `PaperPosition.update_price(...)`: canonical place to call `derive_pnl_pct`.
- `Aribot.update_positions(...)`: consumes updated `pnl_percentage` for stop/trail/partial decisions.
- `Aribot.reconcile_positions_on_startup(...)`: recomputes startup `pnl_percentage` before recovery actions.
- `Aribot.persist_position(...)` and `Aribot.record_closed_trade(...)`: persist derived `pnl_percentage`.
- `Aribot.open_position(...)` + `extract_order_fill(...)`: ensure fill-derived entry (`avg_fill_price`) is persisted.

In `startup_reconciler.py`:
- `upsert_local_position_from_exchange(...)`: bootstrap with no exchange percent reads.
- `archive_local_position_as_closed(...)`: unify to shared `derive_pnl_pct` for archived close rows.

## Startup Behavior Contract

At startup, after reconciliation and before any recovery close:
1. Position has persisted `entry_price` (live: fill-derived average, not signal price).
2. Bot fetches current market price.
3. Bot computes `pnl_percentage = derive_pnl_pct(entry_price, current_price, side)`.
4. Stop/trailing decisions run using that derived value only.

This explicitly prevents false stop triggers caused by leverage-amplified exchange percentage fields.

## Test Requirements for Branch A

Unit tests:
- `derive_pnl_pct` long/short positive and negative cases.
- zero/invalid entry handling returns `0.0`.
- side aliases (`buy/sell`) match (`long/short`).

Behavior tests:
- Startup reconciliation scenario:
  - local/exchange entry `100`
  - current market `97`
  - side `long`
  - computed `pnl_percentage == -3.0`
  - no reads of exchange percentage fields
  - stop logic behavior follows configured threshold in `should_close_for_loss` using derived value only.

Static safety check:
- codebase grep for forbidden Bybit percent fields in strategy logic.

## Non-Goals (Branch A)

- Native SL/TP/trailing exchange orders (Change 2)
- Leverage setter workflow (Change 3)
- Any SQLite schema additions

## Rollout Notes

- Prefer introducing `derive_pnl_pct` once and reusing in both files.
- Keep function pure and deterministic for easy unit testing.
- Preserve existing net PnL accounting (`pnl`) for balance and reporting; only `pnl_percentage` semantics are standardized to price movement.

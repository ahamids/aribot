# Branch A Diff Summary (Price-Based PnL Derivation)

Date: 2026-03-29
Scope: Branch A only (price-based pnl_percentage derivation and startup reconciliation safety)

## Files Changed

### aribot/runtime/engine.py
- Added `derive_pnl_pct(entry_price, current_price, side)` as the canonical price-based PnL percentage helper.
- Updated `PaperPosition.update_price(...)` so `pnl_percentage` is always derived by `derive_pnl_pct(...)`.
- Preserved existing net cash PnL (`pnl`) and fee accounting logic; only percentage semantics were standardized.
- Startup recovery path (`reconcile_positions_on_startup`) now benefits automatically because it already calls `pos.update_price(...)` before stop checks.

### startup_reconciler.py
- Updated `archive_local_position_as_closed(...)` to compute archived `closed_trades.pnl_percentage` via `derive_pnl_pct(...)` for consistency with runtime behavior.
- Kept `upsert_local_position_from_exchange(...)` bootstrap behavior at `pnl_percentage=0.0` and `current_price=entry_price`.
- No exchange margin-based percentage fields are read or persisted for strategy PnL percentage.

### test_live_bot.py
- Added Branch A unit/behavior tests:
  - `test_13_derive_pnl_pct_price_based_long_short`
  - `test_14_startup_reconciler_ignores_exchange_percentage_fields`
  - `test_15_recovery_recomputes_price_based_pct_before_stop_checks`
- Added `FakeExchangeWithPctFields` fixture to simulate exchange payloads that include margin-based percentage fields and verify they are ignored.
- Registered tests 13-15 in `main()` and `criteria_map`.

## Test Runs

Command run:
- `python -c "import test_live_bot as t; print('test_10_entry_order_sets_leverage_before_create_order:', t.test_10_entry_order_sets_leverage_before_create_order()); print('test_11_entry_order_aborts_when_set_leverage_fails:', t.test_11_entry_order_aborts_when_set_leverage_fails()); print('test_12_non_entry_order_skips_leverage_precheck:', t.test_12_non_entry_order_skips_leverage_precheck()); print('test_13_derive_pnl_pct_price_based_long_short:', t.test_13_derive_pnl_pct_price_based_long_short()); print('test_14_startup_reconciler_ignores_exchange_percentage_fields:', t.test_14_startup_reconciler_ignores_exchange_percentage_fields()); print('test_15_recovery_recomputes_price_based_pct_before_stop_checks:', t.test_15_recovery_recomputes_price_based_pct_before_stop_checks())"`

Results:
- PASS: `test_10_entry_order_sets_leverage_before_create_order`
- PASS: `test_11_entry_order_aborts_when_set_leverage_fails`
- PASS: `test_12_non_entry_order_skips_leverage_precheck`
- PASS: `test_13_derive_pnl_pct_price_based_long_short`
- PASS: `test_14_startup_reconciler_ignores_exchange_percentage_fields`
- PASS: `test_15_recovery_recomputes_price_based_pct_before_stop_checks`

## Scope Guardrail
- Branch B native stop/TP/trailing implementation was not added in this change set.

# Branch B Diff Summary (Native SL/TP/Trailing Integration)

Date: 2026-03-29
Scope: Branch B only (Bybit set_trading_stop integration, non-blocking warnings, schema/migration, startup re-arm)

## Files Changed

### order_executor.py
- Added Branch B native stop manager methods on OrderExecutor:
  - set_native_initial_protection(symbol, side, entry_price)
  - set_native_trailing(symbol)
  - clear_native_protection(symbol)
  - ensure_native_protection_for_position(symbol, side, entry_price, trailing_active)
- Added internal helper _set_trading_stop_safe(...) with warning-only failure semantics.
- Native-stop operations now return structured status payloads with:
  - ok
  - operation
  - warnings
  - native_sl_active
  - native_tp_active
  - native_trail_active
  - native_sl_price
- Implemented exact Branch B parameters:
  - Initial SL with slTriggerBy=MarkPrice and positionIdx=0
  - Final TP (+5%) safety fallback
  - Trailing callback trailingStop=0.015
  - Fixed SL/TP clear on trailing activation
  - Clear-all on close with fallback None payload
- All set_trading_stop failures are logged as WARNING and returned to callers, never raised as blocking errors.

### aribot/runtime/engine.py
- Extended positions schema in setup_database with:
  - native_sl_active INTEGER DEFAULT 0
  - native_tp_active INTEGER DEFAULT 0
  - native_trail_active INTEGER DEFAULT 0
  - native_sl_price REAL
- Added lightweight in-place migration for existing positions tables to add missing native columns.
- Extended PaperPosition with native state fields mirroring persisted columns.
- Extended load_state and persist_position to load/persist native state columns.
- Open flow integration:
  - After position creation and persistence, attempts native initial protection (SL + final TP safety).
  - Failure is warning-only and does not block open.
- Trailing transition integration in update_positions:
  - On internal trailing activation, calls native trailing setup and clears fixed SL/TP.
  - Failure is warning-only and does not block position management.
- Close flow integration:
  - Attempts clear_native_protection before row deletion.
  - Always clears local native flags and persists once before remove.
  - Failure is warning-only and does not block close.
- Added concise Copilot-style prompt comments around complex orchestration segments.
- Wired startup reconciler with native_stop_executor when live execution is enabled.

### startup_reconciler.py
- Added optional native_stop_executor dependency.
- Extended load_local_open_positions with compatibility-safe native/trailing field loading even if columns are absent.
- Added startup native re-arm pass for overlap positions:
  - If local native flags are all off, calls ensure_native_protection_for_position.
  - Uses local trailing_stop_active to choose fixed SL/TP or trailing restore path.
  - On success, persists native flags via update_local_native_flags.
  - On failure, records warning item only.
- Re-arm warnings do not fail startup gate.
- Added concise Copilot-style prompt comment around re-arm orchestration.

### migrate_live_schema.py
- Added positions migration columns for Branch B:
  - native_sl_active INTEGER DEFAULT 0
  - native_tp_active INTEGER DEFAULT 0
  - native_trail_active INTEGER DEFAULT 0
  - native_sl_price REAL
- Migration remains idempotent via existing PRAGMA table_info checks.

### test_live_bot.py
- Updated seed_positions_db positions schema to include Branch B native columns.
- Added fake helpers for Branch B behavior:
  - FakeExchangeTradingStop
  - FakeNativeStopExecutor
- Added Branch B tests:
  - test_16_native_initial_protection_warns_without_raising
  - test_17_open_position_continues_when_native_initial_fails
  - test_18_trailing_activation_sets_native_trailing_and_clears_fixed
  - test_19_close_position_clears_native_non_blocking
  - test_20_startup_reconciler_rearms_missing_native_stops
- Registered tests 16-20 in main() and criteria_map.

## Test Outcomes (Relevant Branch B + impacted regression checks)

Commands run:
- python -c "import test_live_bot as t; tests=[('test_10_entry_order_sets_leverage_before_create_order', t.test_10_entry_order_sets_leverage_before_create_order), ('test_11_entry_order_aborts_when_set_leverage_fails', t.test_11_entry_order_aborts_when_set_leverage_fails), ('test_12_non_entry_order_skips_leverage_precheck', t.test_12_non_entry_order_skips_leverage_precheck), ('test_13_derive_pnl_pct_price_based_long_short', t.test_13_derive_pnl_pct_price_based_long_short), ('test_14_startup_reconciler_ignores_exchange_percentage_fields', t.test_14_startup_reconciler_ignores_exchange_percentage_fields), ('test_15_recovery_recomputes_price_based_pct_before_stop_checks', t.test_15_recovery_recomputes_price_based_pct_before_stop_checks), ('test_16_native_initial_protection_warns_without_raising', t.test_16_native_initial_protection_warns_without_raising), ('test_17_open_position_continues_when_native_initial_fails', t.test_17_open_position_continues_when_native_initial_fails), ('test_18_trailing_activation_sets_native_trailing_and_clears_fixed', t.test_18_trailing_activation_sets_native_trailing_and_clears_fixed), ('test_19_close_position_clears_native_non_blocking', t.test_19_close_position_clears_native_non_blocking), ('test_20_startup_reconciler_rearms_missing_native_stops', t.test_20_startup_reconciler_rearms_missing_native_stops)];\nfor name, fn in tests:\n    print(name + ':', fn())"
- python -c "import test_live_bot as t; tests=[('test_18_trailing_activation_sets_native_trailing_and_clears_fixed', t.test_18_trailing_activation_sets_native_trailing_and_clears_fixed), ('test_19_close_position_clears_native_non_blocking', t.test_19_close_position_clears_native_non_blocking), ('test_20_startup_reconciler_rearms_missing_native_stops', t.test_20_startup_reconciler_rearms_missing_native_stops)];\nfor name, fn in tests:\n    print(name + ':', fn())"

Results:
- PASS: test_10_entry_order_sets_leverage_before_create_order
- PASS: test_11_entry_order_aborts_when_set_leverage_fails
- PASS: test_12_non_entry_order_skips_leverage_precheck
- PASS: test_13_derive_pnl_pct_price_based_long_short
- PASS: test_14_startup_reconciler_ignores_exchange_percentage_fields
- PASS: test_15_recovery_recomputes_price_based_pct_before_stop_checks
- PASS: test_16_native_initial_protection_warns_without_raising
- PASS: test_17_open_position_continues_when_native_initial_fails
- PASS: test_18_trailing_activation_sets_native_trailing_and_clears_fixed
- PASS: test_19_close_position_clears_native_non_blocking
- PASS: test_20_startup_reconciler_rearms_missing_native_stops

Notes:
- Branch B set_trading_stop integration is warning-only by design and intentionally non-blocking on open/update/close/re-arm paths.
- Internal stop/trailing logic remains primary; native controls are fallback protection.
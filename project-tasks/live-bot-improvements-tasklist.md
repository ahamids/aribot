# Live Bot Improvements Atomic Task List

## Spec-to-Repo File Mapping
- position_manager.py -> usdt_paper_bot_v2.py
- reconciler.py -> startup_reconciler.py
- live_bot.py -> order_executor.py
- db_schema.py -> usdt_paper_bot_v2.py (setup_database) and migrate_live_schema.py (migration path)
- migrate_v2_to_live.sql -> migrate_live_schema.py

## Ordered Implementation Tasks (C -> A -> B)

1. Task C1: Add leverage error type and private leverage pre-check in executor
- Change: C (leverage setter)
- Target files: order_executor.py
- Dependencies: []
- Work: Add LeverageSetError and _ensure_leverage(symbol, leverage) that calls exchange.set_leverage with buyLeverage and sellLeverage, logs success, and raises LeverageSetError on any exception.
- Acceptance criterion: Calling _ensure_leverage for a symbol invokes set_leverage with both buyLeverage and sellLeverage and raises LeverageSetError when the call fails.

2. Task C2: Enforce leverage pre-check before every exchange market order
- Change: C (leverage setter)
- Target files: order_executor.py
- Dependencies: [1]
- Work: Extend execute_order to accept leverage, require leverage for non-dry-run market orders, call _ensure_leverage immediately before create_order, and abort order placement on leverage failure.
- Acceptance criterion: In non-dry-run mode, a leverage-setting failure prevents create_order from being called and returns a failed OrderResult.

3. Task C3: Thread leverage value from strategy to executor order calls
- Change: C (leverage setter)
- Target files: usdt_paper_bot_v2.py
- Dependencies: [2]
- Work: Update submit_market_order signature to accept leverage and pass it to execute_order; provide leverage from get_leverage_for_symbol for entry, partial exits, and full exits so every live market order has an explicit leverage value.
- Acceptance criterion: All live market order callsites in the bot pass a leverage argument into submit_market_order.

4. Task C4: Add leverage-ordering regression tests
- Change: C (leverage setter)
- Target files: test_live_bot.py
- Dependencies: [3]
- Work: Add unit tests that verify set_leverage is called before create_order and that leverage failure aborts order submission.
- Acceptance criterion: New leverage tests fail if create_order executes without a prior successful set_leverage call.

5. Task A1: Introduce a single price-based pnl percentage helper
- Change: A (price-based pnl derivation)
- Target files: usdt_paper_bot_v2.py
- Dependencies: [4]
- Work: Add a helper derive_pnl_pct(entry_price, current_price, side) using the spec formulas for long and short and use it as the canonical pnl percentage source.
- Acceptance criterion: The helper returns -2.5 for long(entry=100,current=97.5) and -2.5 for short(entry=100,current=102.5).

6. Task A2: Refactor position price refresh to use price-derived pnl percentage
- Change: A (price-based pnl derivation)
- Target files: usdt_paper_bot_v2.py
- Dependencies: [5]
- Work: Update PaperPosition.update_price so pnl_percentage is derived from price movement and side, while pnl amount can remain fee-adjusted.
- Acceptance criterion: Position stop-loss checks in update_positions are driven by the price-derived pnl_percentage and no margin-relative exchange field.

7. Task A3: Ensure startup recovery path uses the same derived pnl percentage
- Change: A (price-based pnl derivation)
- Target files: usdt_paper_bot_v2.py
- Dependencies: [6]
- Work: Verify reconcile_positions_on_startup refreshes position state through the updated price-derivation path and does not source pnl percentage from exchange position percentage fields.
- Acceptance criterion: On restart, recovered positions compute pnl_percentage from current_price and entry_price only.

8. Task A4: Align reconciler reconstruction with derived price model and avg fill entry
- Change: A (price-based pnl derivation)
- Target files: startup_reconciler.py
- Dependencies: [7]
- Work: Ensure exchange-to-local upsert and reconstruction logic keeps entry_price aligned to avg fill semantics where available and does not read margin-relative pnl percentage from exchange payloads.
- Acceptance criterion: startup_reconciler.py contains no reads of exchange percentage/unrealizedPnl fields for local pnl_percentage writes.

9. Task A5: Add pnl derivation and restart safety tests
- Change: A (price-based pnl derivation)
- Target files: test_live_bot.py
- Dependencies: [8]
- Work: Add tests for long and short pnl derivation and a reconciliation restart case proving no false stop trigger from margin-based pnl artifacts.
- Acceptance criterion: New tests pass only when pnl_percentage equals the price-derived formula and restart does not force a false stop at safe price moves.

10. Task B1: Add native stop state columns to schema and migration
- Change: B (native stop/TP/trail layer)
- Target files: usdt_paper_bot_v2.py, migrate_live_schema.py
- Dependencies: [9]
- Work: Add native_sl_active, native_tp_active, native_trail_active, native_sl_price to positions table in setup_database migration path and migrate_live_schema.py idempotent column migration.
- Acceptance criterion: Running migration on an existing db produces all four native-stop columns without data loss.

11. Task B2: Implement native trading-stop API wrappers in executor
- Change: B (native stop/TP/trail layer)
- Target files: order_executor.py
- Dependencies: [10]
- Work: Add methods to set open-time SL and final TP, activate trailing fallback, clear superseded SL/TP when trail is set, and clear all native stops on close via exchange.set_trading_stop with Bybit params and warning-only failure handling.
- Acceptance criterion: set_trading_stop exceptions are caught and logged as warnings without propagating and without blocking order flow.

12. Task B3: Wire native stop lifecycle into bot position lifecycle
- Change: B (native stop/TP/trail layer)
- Target files: usdt_paper_bot_v2.py
- Dependencies: [11]
- Work: On live open set native SL and safety TP using entry fill price; when trailing activates set native trailing and clear fixed SL/TP; on any close clear all native stops and persist native state flags/prices.
- Acceptance criterion: Opening a live position attempts native SL/TP setup and closing it attempts native stop cleanup every time.

13. Task B4: Add startup native-stop remediation in reconciler
- Change: B (native stop/TP/trail layer)
- Target files: startup_reconciler.py
- Dependencies: [12]
- Work: During startup reconciliation, detect positions missing native protection flags and request a native stop reset pass for those symbols.
- Acceptance criterion: Reconciler report path includes remediation for open positions that have no native SL/trail state recorded.

14. Task B5: Add native stop end-to-end tests
- Change: B (native stop/TP/trail layer)
- Target files: test_live_bot.py
- Dependencies: [13]
- Work: Add tests validating native SL appears after open, trailing fallback is set when internal trail activates, and native stops are cleared after close.
- Acceptance criterion: New native-stop tests fail unless open sets protection and close clears it.

## Dependency Chain Summary
- C path: 1 -> 2 -> 3 -> 4
- A path: 5 -> 6 -> 7 -> 8 -> 9
- B path: 10 -> 11 -> 12 -> 13 -> 14
- Global order: complete C path before A path, and complete A path before B path.

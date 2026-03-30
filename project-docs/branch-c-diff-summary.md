# Branch C Diff Summary (Leverage Setter)

Date: 2026-03-29
Scope: Branch C only (explicit leverage setting before entry market orders)

## Files Changed

### order_executor.py
- Added `LeverageSetError` for explicit leverage setup failures.
- Extended `OrderExecutor.execute_order(...)` signature with keyword-only arguments:
  - `order_reason: str = 'unspecified'`
  - `leverage: Optional[float] = None`
- Added entry-only precheck in `execute_order`:
  - When `order_reason == 'entry'`, require leverage and call `_ensure_leverage(symbol, leverage)` before `create_order`.
  - Abort early if leverage is missing/invalid or `set_leverage` fails.
- Added `_ensure_leverage(symbol, leverage)`:
  - Validates leverage numeric and `> 0`.
  - Calls Bybit leverage API via ccxt with both `buyLeverage` and `sellLeverage`.
  - Logs success line: `Leverage confirmed: {symbol} = {leverage}x`.
  - Raises `LeverageSetError` with symbol/leverage context on failure.
- Added `except LeverageSetError` path to mark idempotency intent failed and return failed `OrderResult` without placing an order.
- Added one concise inline comment where entry leverage gating occurs.

### usdt_paper_bot_v2.py
- Updated `submit_market_order(...)` signature to accept `leverage=None`.
- Wired pass-through to executor:
  - `order_reason=reason`
  - `leverage=leverage`
- Updated `open_position(...)` entry order call to pass computed `leverage` into `submit_market_order(...)`.
- Non-entry flows (close/partial-profit/etc.) remain unchanged and omit leverage.

### test_live_bot.py
- Added `FakeExchangeLeverageOrder` to capture call order and simulate set_leverage failure.
- Added Branch C tests:
  - `test_10_entry_order_sets_leverage_before_create_order`
  - `test_11_entry_order_aborts_when_set_leverage_fails`
  - `test_12_non_entry_order_skips_leverage_precheck`
- Registered tests 10-12 in `main()` and `criteria_map`.

## Test Outcomes (Relevant Branch C + touched executor paths)

Command run:
- `python -c "import test_live_bot as t; print('test_5_dry_run:', t.test_5_dry_run()); print('test_6_idempotency:', t.test_6_idempotency()); print('test_10_entry_order_sets_leverage_before_create_order:', t.test_10_entry_order_sets_leverage_before_create_order()); print('test_11_entry_order_aborts_when_set_leverage_fails:', t.test_11_entry_order_aborts_when_set_leverage_fails()); print('test_12_non_entry_order_skips_leverage_precheck:', t.test_12_non_entry_order_skips_leverage_precheck())"`

Results:
- PASS: `test_5_dry_run`
- PASS: `test_6_idempotency`
- PASS: `test_10_entry_order_sets_leverage_before_create_order`
- PASS: `test_11_entry_order_aborts_when_set_leverage_fails`
- PASS: `test_12_non_entry_order_skips_leverage_precheck`

Notes:
- Branches A and B were not implemented in this change set.

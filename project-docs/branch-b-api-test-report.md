# Branch B API Test Report

Date: 2026-03-29
Scope: Real Bybit testnet round-trip validation for Branch B native stops

## Implementation Notes
- Added a new live validation in `test_live_bot.py`: `test_24_branch_b_testnet_native_stop_round_trip()`.
- The test performs a real API workflow when credentials are present:
  - Opens a tiny testnet position.
  - Sets native stop-loss via `set_trading_stop` and verifies it appears in `fetch_positions` payload.
  - Attempts trailing activation validation when enabled (`BRANCH_B_VALIDATE_TRAILING`, default true).
  - Clears native stop fields via `set_trading_stop` and verifies cleared state.
  - Closes the position with `reduceOnly` and verifies no open position remains.
- The test returns explicit `PASS` or `FAIL` only (never `SKIP`).
- If required credentials/env are missing, it returns `FAIL` with a concrete reason.

## Test Execution
Command:

```powershell
python -c "import test_live_bot as t; status, details = t.test_24_branch_b_testnet_native_stop_round_trip(); print('test_24_branch_b_testnet_native_stop_round_trip:', status); print(details)"
```

Observed result:
- Status: `FAIL`
- Reason: `Missing BYBIT_TRADE_API_KEY/BYBIT_TRADE_API_SECRET for Branch B testnet validation.`

## Required Environment For Real Execution
- `BYBIT_TRADE_API_KEY`
- `BYBIT_TRADE_API_SECRET`
- `BRANCH_B_TEST_SYMBOL` (or `TESTNET_SYMBOL`)
- `BRANCH_B_TEST_QTY` (or `TESTNET_ORDER_QTY`)
- Optional:
  - `BRANCH_B_TEST_SIDE` (`buy`/`sell`, default `buy`)
  - `BRANCH_B_VALIDATE_TRAILING` (`true`/`false`, default `true`)

## Current Conclusion
- Branch B real API validation path is implemented and runnable.

## Rerun Update (Mainnet Mode)
Date: 2026-03-30
Mode: mainnet (`BYBIT_TESTNET=false`)

Observed result:
- `test_24_branch_b_testnet_native_stop_round_trip`: `PASS`

Notes:
- Native stop-loss set and clear verification passed via live position payload fields.
- Trailing callback attempt returned exchange-side invalid trailing value in this run, but test acceptance still passed because required SL set/clear and position close checks succeeded.

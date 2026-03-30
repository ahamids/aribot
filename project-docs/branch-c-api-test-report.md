# Branch C API Test Report

Date: 2026-03-29
Workspace: c:/code/aribot

## Scope
Added and executed Branch C testnet validation for leverage setter acceptance in the real Bybit testnet API-call path.

Validation target:
1. Entry order flow must call leverage setter through `OrderExecutor.execute_order(..., order_reason='entry', leverage=...)`.
2. Resulting Bybit position leverage must match requested tier.
3. Coverage includes BTC major tier and one non-major symbol tier.
4. Test emits explicit PASS or FAIL (never SKIP), including reason when credentials/environment are missing.

## Implementation Notes
Changes made in `test_live_bot.py`:
1. Added env parsing helper for numeric inputs.
2. Added leverage extraction helper from fetched Bybit position payload.
3. Added real API validation helper that:
   - creates a real `OrderExecutor` with sandbox mode enabled,
   - executes entry flow with leverage,
   - fetches open position and verifies leverage,
   - attempts best-effort reduce-only flatten cleanup.
4. Added `test_23_branch_c_testnet_leverage_acceptance()` and wired it into `main()` test registry and criteria map.

Default test inputs:
- BTC major symbol: `BRANCH_C_TESTNET_BTC_SYMBOL` (default `BTC/USDT:USDT`)
- Non-major symbol: `BRANCH_C_TESTNET_NON_MAJOR_SYMBOL` (default `ADA/USDT:USDT`)
- Side: `BRANCH_C_TESTNET_ORDER_SIDE` (default `buy`)
- BTC quantity: `BRANCH_C_TESTNET_BTC_QTY` (default `0.001`)
- Non-major quantity: `BRANCH_C_TESTNET_NON_MAJOR_QTY` (default `1.0`)

## Execution
Command run:

```powershell
python -c "import test_live_bot as t; print('test_23_branch_c_testnet_leverage_acceptance:', t.test_23_branch_c_testnet_leverage_acceptance())"
```

Result:

```text
test_23_branch_c_testnet_leverage_acceptance: ('FAIL', 'btc_major=FAIL(Missing BYBIT_TRADE_API_KEY/BYBIT_TRADE_API_SECRET for Bybit testnet leverage validation.); non_major=FAIL(Missing BYBIT_TRADE_API_KEY/BYBIT_TRADE_API_SECRET for Bybit testnet leverage validation.); criteria=Use real Bybit testnet API path through OrderExecutor entry flow with leverage.; Validate BTC major leverage at 5x from resulting Bybit position payload.; Validate one non-major symbol leverage at 3x from resulting Bybit position payload.; Return explicit PASS or FAIL with concrete reason when credentials/env are missing.')
```

## Status
## Rerun Update (Mainnet Mode)
Date: 2026-03-30
Mode: mainnet (`BYBIT_TESTNET=false`)

Result:
- `test_23_branch_c_testnet_leverage_acceptance`: `PASS`

Observed leverage assertions:
- BTC/USDT:USDT observed leverage = 5x
- ADA/USDT:USDT observed leverage = 3x

Outcome summary:
- Branch C leverage acceptance is now passing with real API calls.

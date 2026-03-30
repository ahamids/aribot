# Branch A API Test Report

Date: 2026-03-29
Scope: Branch A testnet validation for price-based PnL derivation and restart/reconciliation stop-safety behavior.

## Implementation Notes

Updated `test_live_bot.py` with:
- Helper functions to normalize symbols, resolve required testnet symbol env vars, and extract side/contracts/margin-relative percentage fields from Bybit position payloads.
- `test_21_branch_a_testnet_price_based_pnl_from_entry_and_ticker`
  - Uses real Bybit testnet API calls when credentials exist.
  - Pulls entry fill from testnet position data and live ticker price.
  - Validates price-based PnL derivation via `derive_pnl_pct` and does not use Bybit percentage fields as source of truth.
  - Returns explicit `PASS` or `FAIL` only.
- `test_22_branch_a_restart_reconcile_ignores_margin_pct_no_false_stop`
  - Uses real Bybit testnet position and live ticker data when credentials exist.
  - Seeds stale margin-relative PnL% into a restart/reconciliation style flow.
  - Validates reconciliation recomputes PnL from prices and does not trigger a false immediate stop.
  - Returns explicit `PASS` or `FAIL` only.

Both tests fail fast with clear reasons when credentials or required env are missing.

## Execution

Command run:

```powershell
python -c "import test_live_bot as t; tests=[('test_21_branch_a_testnet_price_based_pnl_from_entry_and_ticker', t.test_21_branch_a_testnet_price_based_pnl_from_entry_and_ticker), ('test_22_branch_a_restart_reconcile_ignores_margin_pct_no_false_stop', t.test_22_branch_a_restart_reconcile_ignores_margin_pct_no_false_stop)];
for name, fn in tests:
    status, details = fn();
    print(name + ': ' + status);
    print(details)
"
```

Observed output:

- test_21_branch_a_testnet_price_based_pnl_from_entry_and_ticker: `FAIL`
  - Reason: Missing `BYBIT_TRADE_API_KEY`/`BYBIT_TRADE_API_SECRET`; cannot run real Branch A API validation.
- test_22_branch_a_restart_reconcile_ignores_margin_pct_no_false_stop: `FAIL`
  - Reason: Missing `BYBIT_TRADE_API_KEY`/`BYBIT_TRADE_API_SECRET`; cannot run restart reconciliation API validation.

## Conclusion

Result status is explicit and non-skipping as required (`PASS`/`FAIL` only).
Current run is `FAIL` for both Branch A tests due to missing required testnet credentials in environment.

To execute real API validations successfully, set:
- `BYBIT_TRADE_API_KEY`
- `BYBIT_TRADE_API_SECRET`
- `BRANCH_A_TESTNET_SYMBOL` (preferred) or `TESTNET_SYMBOL`

## Rerun Update (Mainnet Mode)

Date: 2026-03-30
Mode: mainnet (`BYBIT_TESTNET=false`)

Observed output:

- test_21_branch_a_testnet_price_based_pnl_from_entry_and_ticker: `PASS`
- test_22_branch_a_restart_reconcile_ignores_margin_pct_no_false_stop: `PASS`

Outcome summary:
- Branch A real-call validation is now passing with live exchange responses.

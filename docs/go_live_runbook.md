# Aribot Live Trading Go-Live Runbook

This runbook defines the mandatory release sequence for moving from testnet to scaled mainnet trading.

## Global Rules

1. Do not skip stages.
2. If any stage fails exit criteria, execute rollback and restart from that stage after remediation.
3. Capture evidence for each stage in a dated folder, for example: `docs/evidence/YYYY-MM-DD-go-live/`.
4. Any CRITICAL reconciliation failure or ghost position detection is an immediate stop condition.

## Stage 1 - Final Testnet Run (48 Hours)

### Objective

Run the bot on Bybit testnet for 48 continuous hours with full lifecycle behavior validated.

### Entry Criteria

1. `BOT_MODE=shadow` or `BOT_MODE=live` as required for testnet validation.
2. `BYBIT_TESTNET=true`.
3. Startup secret validation passes.
4. Startup reconciliation passes with no manual-review block.
5. Kill switch file is absent.
6. Telegram alerting configured and reachable.

### Required Validation During Stage

1. At least 3 complete trade cycles are observed.
2. Across those cycles, lifecycle coverage includes:
   - entry
   - partial exits
   - trailing stop exit
   - time exit

### Exit Criteria

1. Runtime duration is at least 48 hours without process instability.
2. At least 3 complete trade cycles are documented with timestamps and symbols.
3. Evidence shows all required lifecycle events occurred.
4. No unhandled exceptions causing process crash.
5. No unresolved reconciliation anomalies.

### Rollback Procedure

1. Trigger kill switch immediately if unsafe behavior is observed.
2. Preserve logs and DB snapshot:
   - `observability.jsonl`
   - bot runtime log
   - SQLite DB file
3. Set deployment state to `HOLD_TESTNET`.
4. Open incident record with failing symbol/time/event details.
5. Patch and re-run Stage 1 from hour 0 after fix validation.

## Stage 2 - Mainnet Dry Run (24 Hours)

### Objective

Run against mainnet market data for 24 hours with `DRY_RUN=true`, confirming full signal and risk observability while placing zero orders.

### Entry Criteria

1. Stage 1 signed off.
2. `BYBIT_TESTNET=false`.
3. `DRY_RUN=true`.
4. Idempotency path enabled in executor.
5. Startup reconciliation passes.

### Required Validation During Stage

1. Signals are produced and logged normally.
2. Risk events are emitted when triggered by conditions.
3. No exchange order placement occurs.

### Exit Criteria

1. Runtime duration is at least 24 continuous hours.
2. `test_live_bot.py` dry-run and idempotency scenarios pass.
3. Order ledger confirms no real order IDs were created from this stage.
4. Structured logs show expected signal/risk event flow.

### Rollback Procedure

1. If any real order is detected, immediately engage kill switch.
2. Revert environment to safe mode:
   - `DRY_RUN=true`
   - optionally `BYBIT_TESTNET=true` until root cause is fixed
3. Archive evidence and identify bypass path that allowed order placement.
4. Block promotion to Stage 3 until a repeat 24-hour clean dry run passes.

## Stage 3 - Mainnet Live Minimal Capital (5 Trading Days)

### Objective

Go live on mainnet with minimal capital ($500 starting balance), unchanged strategy parameters, and observe behavior for 5 full trading days.

### Entry Criteria

1. Stage 2 signed off.
2. `BYBIT_TESTNET=false`.
3. `DRY_RUN=false`.
4. Account configured to $500 initial allocated risk capital.
5. Strategy parameters unchanged from validated testnet and dry-run configuration.
6. Startup reconciliation passes at launch.

### Required Validation During Stage

1. Bot runs for 5 full trading days.
2. Reconciliation is clean on any restart.
3. Daily drawdown breaker, stop logic, and kill-switch pathways remain operational.

### Exit Criteria

1. 5 trading days completed with no critical operational incident.
2. No ghost positions detected.
3. No reconciliation startup block caused by bot inconsistency.
4. No unexpected order duplication.
5. Weekly kill switch drill completed at least once within the live period or immediately before scale request.

### Rollback Procedure

1. If drawdown or operational anomaly breaches policy, trigger kill switch.
2. Halt new entries by setting `DRY_RUN=true` before restart.
3. Keep capital fixed at $500 or reduce further until incident review completes.
4. Run startup reconciliation and incident postmortem before any resume.
5. Restart Stage 3 clock (5 full trading days) after remediation.

## Stage 4 - Scale Gate

### Objective

Allow capital increase only when all operational gates remain continuously satisfied.

### Mandatory Scale Conditions

Capital increase is permitted only if all are true:

1. Reconciler passes on every startup.
2. No ghost positions are ever detected.
3. Kill switch is tested successfully once per week.

### Entry Criteria

1. Stage 3 signed off.
2. Evidence package includes startup reconciliation history and weekly kill switch test logs.

### Exit Criteria

1. Scale approval granted by operator after reviewing all three mandatory scale conditions.
2. Capital increase performed in controlled increments with change log entry.

### Rollback Procedure

1. If any mandatory condition fails at any time, freeze scaling immediately.
2. Revert to previous approved capital level.
3. Set operation mode to conservative (`DRY_RUN=true` or reduced capital live) based on severity.
4. Re-open Stage 3 observation until conditions are re-established.

## Required Evidence Checklist Per Stage

1. Runtime start and end timestamps.
2. Environment mode snapshot (`BOT_MODE`, `BYBIT_TESTNET`, `DRY_RUN`).
3. Reconciliation report output for each startup.
4. Kill switch test record when required.
5. Structured log extracts proving required event coverage.
6. Incident log and remediation notes for any deviation.

## Operational Stop Conditions (Any Stage)

1. Ghost position detected.
2. Startup reconciliation fails.
3. Unintended real order during dry run.
4. Repeated order duplication attempt bypassing idempotency.
5. Kill switch malfunction.

If any stop condition occurs, execute rollback for current stage immediately.
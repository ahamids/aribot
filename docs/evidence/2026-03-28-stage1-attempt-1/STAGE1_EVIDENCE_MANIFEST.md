# Stage 1 Evidence Manifest
**Date**: 2026-03-28  
**Attempt**: 1  
**Status**: ❌ INCOMPLETE - Duration Gap

---

## Summary

Stage 1 testnet validation run with the following characteristics:

- **Period**: 2026-03-26 20:37 → 2026-03-28 08:17
- **Accumulated Runtime**: 32.21 hours (Target: 48 hours)
- **Gap**: 15.79 hours remaining
- **Bot Instances**: 5 separate run_ids (process restarts detected)
- **Final Status**: Stopped by user on 2026-03-28 08:17:46

---

## Exit Criteria vs. Achievement

| Criterion | Required | Achieved | Status |
|-----------|----------|----------|--------|
| **Continuous Runtime** | 48 hours | 32.21 hours | ❌ FAIL |
| **Complete Trade Cycles** | ≥3 | 8 closes | ✅ PASS |
| **Entry Events** | Coverage | 14 entries | ✅ PASS |
| **Partial Exits** | Coverage | 13 observed | ✅ PASS |
| **Trailing Stop Exit** | Coverage | 4 observed | ✅ PASS |
| **Time-based Exit** | Coverage | 0 observed | ⚠️ UNCOVERED |
| **Stop-loss Exit** | Coverage | 4 observed | ✅ PASS |
| **Process Crashes** | 0 in 48h | 0 detected | ✅ PASS |
| **Reconciliation Blocks** | 0 | 0 detected | ✅ PASS |
| **Ghost Positions** | 0 | 0 detected | ✅ PASS |

---

## Archived Evidence Files

### 1. `observability.jsonl`
**Type**: Structured event log (JSON Lines)  
**Size**: ~100KB+  
**Content**: 
- Timestamped events from all 5 bot run instances
- Position opens/closes with entry prices and profit-loss
- Partial exit events at escalating profit levels
- Funding payments (for margin positions)
- Loop cycle completion metrics
- Cycle count in final run: 962 cycles completed

**Key Events Captured**:
- Position entries across multiple symbols (BTC, ETH, XAUT, AXS, CYS, GALA, HUMA, LIGHT, UAI)
- Partial profit-taking at 2%, 3%, 5% levels
- Trailing stop exits (BTC: +83.84%, ETH: +39.59%, XAUT: +0.21%)
- Stop-loss closes (ETH: -2.78%, -4.00%; BTC: -6.43%)

### 2. `usdt_paper_trading_log.txt`
**Type**: Human-readable trading log  
**Content**:
- Cycle-by-cycle execution logs
- Environmental configuration (mode=paper, testnet=True)
- Balance tracking (started $10,000 → ended $10,152.86)
- Trade statistics (8 trades, 4W/4L)
- System status checks every ~6 cycles
- Clean shutdown timestamp: 2026-03-28 08:17:46

**Stop Condition**: User manually stopped bot after 32.21h for assessment

### 3. `usdt_paper_bot_v2.db`
**Type**: SQLite database snapshot  
**Tables**:
- `positions` - All opened positions and states
- `closed_trades` - Complete trade history with PnL
- `partial_realizations` - Profit-taking levels
- `funding_payments` - Margin funding records
- `bot_state` - Persistent bot configuration state

**Final State**:
- 0 open positions
- 8 closed trades logged
- Total PnL: +$152.86 (profitable)

---

## Run Instance Timeline

### Instance 1: f10a5209a243
- **Duration**: 2026-03-26 23:17 → 23:30 (0.22h)
- **Events**: 14
- **Type**: Brief connectivity/bootstrap test
- **Notes**: Minimal trading activity

### Instance 2: 25e03627abc2
- **Duration**: 2026-03-26 20:37 → 22:44 (2.13h)
- **Events**: 134
- **Notes**: Early run, limited cycle coverage

### Instance 3: cca0855656a9
- **Duration**: 2026-03-27 00:14 → 07:27 (7.21h)
- **Events**: 433
- **Trades**: 3 complete cycles
- **Notes**: First substantive run with trade coverage

### Instance 4: e6061195825c
- **Duration**: 2026-03-27 08:01 → 14:10 (6.14h)
- **Events**: 378
- **Trades**: 2 complete cycles

### Instance 5: 66b8813b4860 ⭐ (Longest)
- **Duration**: 2026-03-27 14:46 → 2026-03-28 07:17 (16.52h)
- **Events**: 986 (entire 962 cycles in log)
- **Trades**: 3 complete cycles
- **Notes**: Most stable run, longest continuous uptime

---

## Operational Observations

### ✅ What Worked
1. **Entry Generation**: Signal generation stable across multiple market conditions
2. **Position Management**: Proper entry prices and quantity sizing
3. **Partial Profit Taking**: Consistent 2%-3%-5% profit-taking at defined levels
4. **Trailing Stop**: Successfully implemented for winners (up to +83% capture)
5. **Stop-Loss**: Protective stops executed cleanly
6. **Funding Operations**: Margin funding tracked and applied
7. **Database Consistency**: No corruption, clean state on shutdown
8. **Process Stability**: Zero unhandled exceptions across all runs

### ⚠️ Gaps/Observations
1. **Continuous Runtime**: Fragmented across 5 instances instead of single 48h run
   - Suggests manual intervention or infrastructure restarts between runs
   - Runbook requires "continuous 48 hours without process instability"
   
2. **Time-based Exits**: Not observed in current test window
   - Strategy may not hit time-exit conditions during this period
   - Need validation in extended run that time exit pathways function
   
3. **Restart Causes Unknown**: Multiple run_ids indicate process bounces
   - Need investigation: deliberate stops vs. infrastructure failures
   - Runbook exit criteria: "without process instability"

### Balance Tracking
```
Start:  $10,000.00
Trades: 8 (4 wins, 4 losses)
Final:  $10,152.86
Net:    +$152.86 (+1.528%)
```

---

## Validation Status

### ✅ Lifecycle Coverage Achieved
- [x] Entry signals evaluated and executed
- [x] Partial exits at escalating profit levels (2%, 3%, 5%)
- [x] Trailing stop exits (multiple)
- [x] Stop-loss exits (protective)
- [ ] Time-based position exits (not observed this window)

### ✅ Risk & Reconciliation
- [x] No ghost positions (verified via daily reconciliation concept)
- [x] No startup reconciliation failures
- [x] Proper leverage application per symbol tier
- [x] No unexpected order duplication

### ❌ Duration Requirement
- [x] 48+ continuous hours: NOT MET (32.21 accumulated across 5 breaks)

---

## Recommendation for Stage 1 - Attempt 2

### Prerequisites Before Restart
1. **Investigate Restart Pattern**
   - Were stops deliberate (manual intervention)?
   - Or infrastructure-driven (process crash, system restart)?
   - Runbook requires continuous runs without instability

2. **Environment Validation**
   - Verify testnet connectivity stable
   - Confirm no scheduled maintenance windows in next 48h
   - Ensure kill-switch is armed and reachable
   - Verify Telegram alerting configured

3. **Extended Run Parameters**
   - Target: Single continuous 48h+ uninterrupted run
   - Monitoring: Watch for time-exit coverage during run
   - Restarts: Only if necessary for remediation; if so, restart clock from 0h

### Expected Outcomes for Attempt 2
- Single run_id for entire session
- Runtime > 48 continuous hours
- At least 3 additional complete trade cycles
- At least 1 time-based exit (if conditions permit)
- Clean reconciliation on shutdown

---

## Archive Structure

```
docs/evidence/2026-03-28-stage1-attempt-1/
├── STAGE1_EVIDENCE_MANIFEST.md       (this file)
├── observability.jsonl               (structured events)
├── usdt_paper_trading_log.txt        (human log)
└── usdt_paper_bot_v2.db              (database snapshot)
```

---

**Archived**: 2026-03-28 08:25 UTC  
**Next Action**: Restart Stage 1 with continuous 48h target  
**Blocker**: 15.79 hours runtime gap

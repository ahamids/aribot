# Telegram Functional Improvements Task List

## Specification Summary (Exact Scope)
- Add these Telegram management commands:
  - /status
  - /positions
  - /pnl
  - /trades [n]
  - /pause
  - /resume
  - /close SYMBOL (YES confirmation required)
  - /close all (YES confirmation required)
  - /kill (YES confirmation required)
  - /config
- Required command semantics from spec:
  - /status must include mode, regime direction, session PnL, loop cycle count, drawdown %, cooldown state.
  - /positions must include symbol, side, entry, current price, pnl%, trail active.
  - /pnl must show today realized PnL, cumulative PnL, win/loss count (from closed_trades + bot_state).
  - /trades [n] returns last n closed trades with reason; if n omitted, return all trades from today.
  - /pause suspends new entries only; existing positions continue managed.
  - /resume re-enables new entries and logs manual override with timestamp.
  - /close SYMBOL and /close all must require confirmation reply YES.
  - /kill must write kill_switch.flag, trigger close-all flow, and exit code 42 via remote trigger.
  - /config is read-only and must not expose API keys, secrets, or raw env values.
- No extra luxury features outside this scope.

## Codebase Context and File Mapping
- Main runtime: usdt_paper_bot_v2.py
- Existing outbound Telegram alerts: alert_dispatcher.py
- Runtime persistence and state: usdt_bot_v2.db via setup_database/load_state/persist_runtime_state in usdt_paper_bot_v2.py
- Existing close/kill plumbing:
  - close_position(...), close_all_positions_market(...), request_clean_shutdown(...)
  - Kill switch monitor integration in observability.py and runtime loop checks in usdt_paper_bot_v2.py
- Current tests harness: test_live_bot.py

## Ordered Implementation Tasks

1. [x] Task 1: Add inbound Telegram command transport and polling loop integration
- Description:
  - Extend telegram integration beyond outbound send_message to support inbound updates via Telegram getUpdates.
  - Add a non-blocking command poll step to each main loop cycle in usdt_paper_bot_v2.py.
  - Persist last processed update offset in bot_state to prevent duplicate command execution after restart.
- Files to edit:
  - alert_dispatcher.py
  - usdt_paper_bot_v2.py
- Acceptance criteria:
  - Bot can read inbound chat messages for configured TELEGRAM_CHAT_ID.
  - Duplicate Telegram updates are not re-processed across restart.
  - Command polling failure logs warning and does not crash trading loop.
- Test expectations:
  - Unit test with mocked Telegram API verifies update offset progression.
  - Unit test verifies poll errors are warning-only and loop continues.

2. [x] Task 2: Implement command parser, routing, and chat authorization gate
- Description:
  - Add a command router for exact commands in spec only.
  - Parse /trades [n], /close SYMBOL, /close all with strict syntax handling.
  - Reject commands from non-authorized chat IDs.
- Files to edit:
  - usdt_paper_bot_v2.py
  - alert_dispatcher.py (if helper methods are needed)
- Acceptance criteria:
  - Only specified commands are recognized.
  - Unauthorized chat IDs cannot invoke management actions.
  - Invalid syntax returns help text limited to supported commands.
- Test expectations:
  - Parser tests for each command variant and bad input paths.
  - Authorization test proving foreign chat ID commands are ignored/rejected.

3. [x] Task 3: Add runtime snapshot builder for /status response
- Description:
  - Build a reusable status payload function that returns:
    - mode
    - regime direction
    - session PnL
    - loop cycle count
    - drawdown %
    - cooldown state
  - Wire /status to this function and send concise Telegram text output.
- Files to edit:
  - usdt_paper_bot_v2.py
- Acceptance criteria:
  - /status response includes all required fields from spec.
  - Drawdown % uses current_balance vs session_start_balance.
  - Cooldown state reflects in_loss_cooldown() and cooldown_until_utc.
- Test expectations:
  - Unit test validates all required fields are present and formatted.
  - Unit test validates cooldown toggles based on cooldown_until_utc.

4. [x] Task 4: Add /positions command output
- Description:
  - Implement /positions output for all open positions with:
    - symbol
    - side
    - entry
    - current price
    - pnl%
    - trail active
  - Return explicit "no open positions" response when empty.
- Files to edit:
  - usdt_paper_bot_v2.py
- Acceptance criteria:
  - /positions lists every currently tracked open position.
  - pnl% matches position.pnl_percentage.
  - trail active reflects trailing_stop_active state.
- Test expectations:
  - Unit test for empty positions response.
  - Unit test for multi-position formatting and required columns.

5. [x] Task 5: Add /pnl command output from closed_trades + bot_state
- Description:
  - Implement /pnl response containing:
    - today realized PnL
    - cumulative PnL
    - win/loss count this session
  - Use SQLite closed_trades (today filter) plus runtime/bot_state totals.
- Files to edit:
  - usdt_paper_bot_v2.py
- Acceptance criteria:
  - Today realized PnL uses UTC-day filter over closed_trades close_time.
  - Cumulative PnL aligns with total_pnl/current_balance tracking.
  - Win/loss counts align with winning_trades and losing_trades.
- Test expectations:
  - Unit test with seeded in-memory DB verifies today-only realized PnL.
  - Unit test verifies cumulative/session values match bot state.

6. [x] Task 6: Add /trades [n] command output and default behavior
- Description:
  - Implement /trades with optional integer argument n.
  - If n omitted: return all closed trades from today.
  - If n provided: return last n closed trades.
  - Include reason field (stop, trail, time_exit, partial, etc.).
- Files to edit:
  - usdt_paper_bot_v2.py
- Acceptance criteria:
  - /trades returns expected row count for both modes (with/without n).
  - Returned entries include symbol, pnl/pnl%, reason, and close timestamp.
  - Invalid n (non-integer, <=0) returns validation error message.
- Test expectations:
  - Unit tests for /trades, /trades 3, and invalid argument cases.
  - Unit test confirms omitted n defaults to today-only trades.

7. [x] Task 7: Add manual entry control via /pause and /resume
- Description:
  - Introduce manual pause state dedicated to Telegram operator control.
  - /pause disables new entries without touching open position management.
  - /resume re-enables entries and logs manual override timestamp.
  - Integrate manual pause with existing daily drawdown and cooldown entry gating.
- Files to edit:
  - usdt_paper_bot_v2.py
- Acceptance criteria:
  - /pause prevents new entries while update_positions still runs.
  - /resume restores entry scanning eligibility.
  - Log includes manual override action and timestamp for both commands.
- Test expectations:
  - Unit test verifies entry path short-circuits when manual pause is active.
  - Unit test verifies /resume clears manual pause and entry path re-opens.

8. [x] Task 8: Add generic YES-confirmation workflow for dangerous commands
- Description:
  - Implement pending-confirmation state with TTL for:
    - /close SYMBOL
    - /close all
    - /kill
  - Bot must send exact confirmation prompt and execute only on reply YES.
  - Non-YES replies cancel pending action.
- Files to edit:
  - usdt_paper_bot_v2.py
  - alert_dispatcher.py (if reply helpers needed)
- Acceptance criteria:
  - Dangerous commands do not execute before YES reply.
  - YES executes most recent pending action only once.
  - Expired or canceled pending action cannot execute.
- Test expectations:
  - Unit tests for confirm, cancel, timeout, and replay protection.
  - Unit test verifies no side effect occurs before YES.

9. [x] Task 9: Implement /close SYMBOL and /close all command execution
- Description:
  - /close SYMBOL after YES should close target position via existing close path.
  - /close all after YES should close all positions via existing close-all flow.
  - Send success/failure message per action result.
- Files to edit:
  - usdt_paper_bot_v2.py
- Acceptance criteria:
  - /close SYMBOL closes only requested open position.
  - /close all closes all currently open positions.
  - Unknown symbol returns safe error message without side effects.
- Test expectations:
  - Unit test stubbing close_position/close_all_positions_market verifies calls.
  - Unit test verifies proper response when symbol not found.

10. [x] Task 10: Implement /kill remote trigger using existing kill-switch pathway
- Description:
  - After YES confirmation:
    - write kill_switch.flag
    - trigger close-all flow
    - request shutdown with exit code 42
  - Reuse existing request_clean_shutdown(exit_code=42) and runtime break behavior.
- Files to edit:
  - usdt_paper_bot_v2.py
- Acceptance criteria:
  - /kill writes configured kill switch file path.
  - Open positions are sent through close-all flow.
  - Bot exits loop with shutdown_exit_code == 42.
- Test expectations:
  - Unit test verifies file creation, close-all invocation, and exit code state.
  - Integration-style test simulates loop tick and confirms clean break path.

11. [x] Task 11: Implement /config read-only output with strict secret redaction
- Description:
  - Build /config response with key runtime parameters only:
    - mode
    - leverage buckets
    - position cap
    - stop %
  - Explicitly exclude secrets/env raw values (API keys, bot token, chat id, secrets).
- Files to edit:
  - usdt_paper_bot_v2.py
- Acceptance criteria:
  - /config includes required runtime parameters.
  - No secret-bearing values appear in output.
  - Output remains read-only and does not mutate runtime configuration.
- Test expectations:
  - Unit test with known secret env values verifies they never appear in /config text.
  - Unit test verifies listed config fields match runtime values.

12. [x] Task 12: Expand test harness coverage for Telegram management commands
- Description:
  - Add targeted tests in test_live_bot.py for the full command matrix and critical edge cases.
  - Keep tests deterministic by mocking Telegram API and file writes.
- Files to edit:
  - test_live_bot.py
- Acceptance criteria:
  - New tests cover all commands in spec, including confirmation-gated flows.
  - Existing Telegram alert routing tests remain passing.
  - Tests validate no regression to position management and loop stability.
- Test expectations:
  - Add PASS/FAIL tests for:
    - /status, /positions, /pnl, /trades [n]
    - /pause, /resume
    - /close SYMBOL, /close all, /kill confirmation gates
    - /config secret safety

13. [x] Task 13: Operator documentation updates for new command surface
- Description:
  - Update runtime docs to include command list, expected responses, and confirmation behavior.
  - Include kill command operational warning and recovery expectations.
- Files to edit:
  - README.md
  - docs/go_live_runbook.md
- Acceptance criteria:
  - Documentation matches implemented command syntax exactly.
  - Confirmation-gated commands are clearly called out.
  - No unsupported commands are documented.
- Test expectations:
  - Manual verification checklist updated with one command validation step per endpoint.

## Cross-Task Acceptance Gate
- [x] All commands in spec are implemented exactly and reachable from Telegram chat.
- [x] No non-specified command features are introduced.
- [x] Confirmation-required commands execute only on explicit YES reply.
- [x] /pause does not close positions and does not stop ongoing management loop.
- [x] /kill produces close-all plus exit code 42 behavior.
- [x] /config never reveals API keys, secrets, tokens, or raw sensitive env values.

## Recommended Delivery Order
1. Tasks 1-2 (transport and routing foundation)
2. Tasks 3-7 (read commands and pause/resume control)
3. Tasks 8-10 (confirmation-gated dangerous actions)
4. Tasks 11-13 (config safety, tests, docs)

## Critical Risks to Watch During Implementation
- Race/duplication risk if Telegram update offsets are not persisted atomically.
- Safety risk if confirmation state is not single-use and chat-scoped.
- Operational risk if manual pause logic conflicts with existing drawdown/cooldown gates.
- Security risk if /config accidentally leaks token/key values through generic config dumps.

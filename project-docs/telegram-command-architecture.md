# Telegram Command Architecture and UX Foundation

## Purpose
Define a safe, minimal, operator-friendly Telegram management interface for Aribot, constrained to the approved command surface only.

Date: 2026-03-30
Primary runtime: usdt_paper_bot_v2.py
Transport module: alert_dispatcher.py

## Scope Lock (Approved Command Surface Only)

### In scope
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

### Explicitly out of scope
- Any additional commands, aliases, or slash-shortcuts
- Any non-YES dangerous command confirmation protocol
- Any Telegram inline keyboard workflow
- Any runtime configuration mutation command beyond /pause and /resume entry-gating behavior

## Design Goals
- Safety-first control plane over chat with strict authorization and confirmation gates.
- Zero impact to core trading loop stability when Telegram API is degraded.
- Deterministic command execution with restart-safe update offset tracking.
- Operator responses optimized for quick read in Telegram chat.
- No secret leakage in any response format.

## Existing Runtime Anchors
- Outbound Telegram already exists in alert_dispatcher.py via AlertDispatcher.send_message.
- Main loop orchestration exists in Aribot.run.
- Runtime state persistence exists via bot_state table and persist_runtime_state/load_state.
- Kill path exists via request_clean_shutdown(exit_code=42), close_all_positions_market, and kill switch monitor.
- Position close path exists via close_position(symbol, reason).

## Target Architecture

### Subsystem boundaries
1. Transport boundary (alert_dispatcher.py)
- Keep send_message behavior unchanged.
- Add read-side API wrapper for getUpdates polling.
- Return parsed update objects and next offset hint.
- Never raise transport exceptions across boundary; return structured failure.

2. Command domain boundary (usdt_paper_bot_v2.py)
- Add parser, router, authorization gate, and confirmation workflow.
- Produce pure response payload strings for Telegram chat.
- Execute side effects only in handlers after validation and confirmation checks.

3. State boundary (SQLite bot_state)
- Persist inbound offset, manual pause state, and pending confirmation payload.
- Use single-writer commit path on command completion to preserve restart safety.

### Proposed module-level additions

In alert_dispatcher.py:
- get_updates(offset: int | None, timeout_seconds: int = 0, limit: int = 25) -> dict
- extract_text_updates(payload: dict) -> list[dict]

In usdt_paper_bot_v2.py:
- poll_telegram_commands_once(cycle_index: int) -> None
- route_telegram_command(chat_id: str, text: str, update_id: int, now_utc: datetime) -> str | None
- parse_telegram_command(text: str) -> dict
- is_authorized_chat(chat_id: str) -> bool
- build_status_snapshot(cycle_index: int) -> dict
- format_* response helpers for each approved command
- dangerous-action workflow helpers:
  - create_pending_confirmation(action: dict, now_utc: datetime)
  - consume_yes_confirmation_if_valid(text: str, now_utc: datetime) -> dict
  - clear_pending_confirmation(reason: str)

## Data Contract and Persistent State

### bot_state keys
- telegram_last_update_id: integer
- telegram_manual_pause_active: 0 or 1
- telegram_manual_pause_updated_at: ISO8601 UTC timestamp
- telegram_pending_confirmation_json: JSON string or null

### Pending confirmation JSON schema
{
  "chat_id": "<authorized chat id>",
  "action_type": "close_symbol|close_all|kill",
  "action_args": {"symbol": "BTC/USDT:USDT"},
  "created_at_utc": "2026-03-30T12:00:00+00:00",
  "expires_at_utc": "2026-03-30T12:02:00+00:00",
  "nonce": "single-use-random-id"
}

Rules:
- TTL: 120 seconds.
- Single active pending action per authorized chat.
- Any new dangerous command overwrites the previous pending action.
- YES consumes pending action exactly once.
- Any non-YES text while pending cancels pending action with a cancellation reply.

## Polling Integration With Main Bot Loop

### Placement in cycle
Insert one polling call early in each cycle, after kill switch check and shutdown check, before update_positions.

Target order per cycle:
1. kill switch monitor check
2. shutdown_requested check
3. poll_telegram_commands_once(cycle)
4. sync_account_balance
5. reset_daily_session_if_needed
6. update_daily_drawdown_pause
7. update_positions
8. entry scan path
9. funding tracking
10. persist_runtime_state

Why this placement:
- Commands like /pause and /close all are applied quickly before new cycle decisions.
- Any poll failure does not block position management and risk controls.

### Polling behavior
- Use short polling timeout 0 to keep cycle duration deterministic.
- Process updates sorted by update_id ascending.
- Advance telegram_last_update_id only after each update is processed or safely ignored.
- Commit offset after each update handling branch to minimize replay on crash.

### Failure semantics
- Transport errors: warning log only, continue cycle.
- Malformed update: warning log, skip and advance offset.
- Unauthorized chat: ignore side effects, optional minimal rejection reply, advance offset.

## Authorization and Command Routing

### Authorization
- Strict chat gate: incoming message chat_id must equal TELEGRAM_CHAT_ID.
- No fallback to username-based or sender-based authorization.
- Unauthorized messages must never trigger any state mutation.

### Command grammar (strict)
- /status
- /positions
- /pnl
- /trades
- /trades <positive integer>
- /pause
- /resume
- /close all
- /close <SYMBOL>
- /kill

Validation rules:
- Case-insensitive command matching, normalized to lowercase.
- Dangerous confirmation accepts exactly YES (case-insensitive), no extra tokens.
- /trades n requires n > 0 integer.
- /close SYMBOL must map to currently open position symbol key.

### Unknown or invalid command response
Return supported command help only, with no mention of non-scoped features.

## Execution Semantics by Command

### Read commands
1. /status
- Returns mode, regime direction, session pnl, loop cycle count, drawdown percent, cooldown state.
- Drawdown percent formula: ((current_balance - session_start_balance) / session_start_balance) * 100.

2. /positions
- For each open position: symbol, side, entry, current, pnl%, trail active.
- Empty case returns explicit no-open-positions text.

3. /pnl
- Today realized pnl from closed_trades close_time filtered to current UTC day.
- Cumulative pnl from runtime totals.
- Win/loss from winning_trades and losing_trades.

4. /trades [n]
- No n: all today trades.
- With n: latest n trades.
- Row fields: symbol, pnl or pnl%, reason, close timestamp.

5. /config
- Read-only output for mode, leverage buckets, position cap, stop percent.
- Never include tokens, API keys, chat id, or raw env values.

### Control commands
6. /pause
- Sets telegram_manual_pause_active = 1.
- Entry scanner must check this flag alongside daily drawdown and cooldown gates.
- Existing open positions remain fully managed.

7. /resume
- Sets telegram_manual_pause_active = 0.
- Logs manual override with UTC timestamp.

### Dangerous commands (confirmation-gated)
8. /close SYMBOL
- Stage pending action and send confirmation prompt.
- On YES within TTL: close_position(symbol, reason='telegram_manual_close').

9. /close all
- Stage pending action and send confirmation prompt.
- On YES within TTL: close_all_positions_market().

10. /kill
- Stage pending action and send confirmation prompt.
- On YES within TTL:
  - write kill_switch_file
  - close_all_positions_market()
  - request_clean_shutdown(exit_code=42)

## Safety Controls

### Confirmation safety
- Pending action is chat-scoped and single-use.
- Expired pending action cannot execute.
- Replay YES after consumption yields no-op response.

### Idempotency and replay safety
- update_id offset persisted in bot_state prevents duplicate execution after restart.
- Dangerous action execution must include one-time nonce check from pending payload.

### Secret safety
- /config constructed from explicit allowlist only.
- Never dump os.environ or object repr containing credentials.

### Loop safety
- poll_telegram_commands_once wrapped in local try/except.
- No command path allowed to crash Aribot.run cycle.

## Telegram UX Foundation (Chat Response System)

### UX principles
- One-screen responses where possible.
- Stable field order for operator muscle memory.
- Human-friendly values with controlled precision.
- Use plain text or simple HTML tags already supported by AlertDispatcher.parse_mode=HTML.

### Response shape conventions
- Header line: command and status.
- Body lines: key-value pairs in fixed order.
- Footer line: timestamp UTC.

### Canonical response templates

1. /status
Status: OK
Mode: live
Regime: BUY
Session PnL: +123.45 USDT
Cycle: 4182
Drawdown: -1.20%
Cooldown: active until 2026-03-30T16:00:00+00:00
Time UTC: 2026-03-30T12:31:45+00:00

2. /positions (non-empty)
Open Positions: 2
- BTC/USDT:USDT | long | entry 70400.00 | current 70812.50 | pnl% +0.59 | trail yes
- ETH/USDT:USDT | short | entry 3520.00 | current 3491.00 | pnl% +0.82 | trail no
Time UTC: 2026-03-30T12:31:45+00:00

3. /positions (empty)
Open Positions: 0
No open positions.
Time UTC: 2026-03-30T12:31:45+00:00

4. /pnl
PnL Snapshot
Today Realized: +55.20 USDT
Cumulative: +312.90 USDT
Session W/L: 7/3
Time UTC: 2026-03-30T12:31:45+00:00

5. /trades 3
Recent Closed Trades: 3
1) BTC/USDT:USDT | +22.10 USDT | +0.74% | TRAILING_STOP | 2026-03-30T11:58:00+00:00
2) ETH/USDT:USDT | -11.40 USDT | -0.41% | stop_loss | 2026-03-30T10:12:00+00:00
3) SOL/USDT:USDT | +8.70 USDT | +0.96% | partial | 2026-03-30T08:21:00+00:00
Time UTC: 2026-03-30T12:31:45+00:00

6. /pause
Entries paused by operator.
Open positions remain managed.
Time UTC: 2026-03-30T12:31:45+00:00

7. /resume
Entries resumed by operator.
Manual override logged.
Time UTC: 2026-03-30T12:31:45+00:00

8. /close SYMBOL prompt
Reply YES to close BTC/USDT:USDT at market.
Expires in 120s.

9. /close all prompt
Reply YES to close all open positions at market.
Expires in 120s.

10. /kill prompt
Reply YES to execute emergency shutdown.
Action: close all positions, write kill switch, exit code 42.
Expires in 120s.

11. /config
Config (read-only)
Mode: live
Leverage Buckets: major=5, large_alt=3, mid_cap=2, default=1
Position Cap: 10
Stop Percent: 2.5
Time UTC: 2026-03-30T12:31:45+00:00

### Error and validation responses
- Invalid syntax:
  - Invalid command format. Use one of: /status, /positions, /pnl, /trades [n], /pause, /resume, /close SYMBOL, /close all, /kill, /config
- Unauthorized chat:
  - Unauthorized chat.
- Confirmation canceled:
  - Pending action canceled.
- Confirmation expired:
  - Pending action expired. Re-issue command.

## Integration Contract for Entry Gating

Current entry gate conditions:
- daily_drawdown_paused
- in_loss_cooldown()

Required addition:
- telegram_manual_pause_active

Behavior:
- If manual pause is active, skip new entries exactly like existing risk pauses.
- Do not change update_positions, close logic, trailing logic, funding tracking, or persistence cadence.

## Observability and Logging Contract
- Log each inbound command event with:
  - update_id
  - chat_id (masked to last 4 chars in logs)
  - command_name
  - authorized boolean
  - action_result
- Emit structured event types:
  - telegram_command_received
  - telegram_command_rejected
  - telegram_command_executed
  - telegram_confirmation_created
  - telegram_confirmation_consumed
  - telegram_confirmation_expired

## Test Architecture Mapping

### Unit tests expected
- Poll offset progression and restart safety.
- Poll error warning-only behavior.
- Parser acceptance and rejection matrix for approved grammar only.
- Authorization gate prevents side effects from foreign chat ids.
- /status payload contains required fields and cooldown state.
- /positions empty and multi-position formatting.
- /pnl UTC-day realized calculation and cumulative/session counts.
- /trades default today and explicit n behavior.
- /pause and /resume entry gating effect.
- Confirmation workflow confirm/cancel/expiry/replay protection.
- /close SYMBOL and /close all call-path verification.
- /kill writes kill switch, closes positions, sets exit code 42.
- /config secret redaction guarantee.

### Integration test expected
- Simulated cycle with command polling ensures loop continues on Telegram transport failures.

## Implementation Sequence (Aligned to Tasklist)
1. Transport read path in alert_dispatcher.py.
2. Polling and offset persistence in usdt_paper_bot_v2.py.
3. Parser, authorization, routing foundation.
4. Read command payload builders and formatters.
5. Manual pause/resume gate integration.
6. Generic confirmation state machine.
7. Dangerous action execution handlers.
8. /config allowlist rendering.
9. Full command matrix tests in test_live_bot.py.
10. Operator docs updates in README.md and docs/go_live_runbook.md.

## Non-Negotiable Acceptance Criteria
- Only approved commands are recognized.
- Dangerous commands execute only after YES confirmation within TTL.
- Polling failures never crash the trading loop.
- /pause never closes positions and never stops position management.
- /kill triggers kill switch file write, close-all flow, and exit code 42 shutdown path.
- /config response never reveals secrets, tokens, or raw sensitive environment values.

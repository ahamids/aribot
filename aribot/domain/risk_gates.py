from __future__ import annotations

import datetime


def should_reset_daily_session(current_utc_day: datetime.date, now_utc: datetime.datetime) -> bool:
    return now_utc.date() != current_utc_day


def compute_drawdown(current_balance: float, session_start_balance: float) -> float | None:
    if session_start_balance <= 0:
        return None
    return (current_balance - session_start_balance) / session_start_balance


def should_trigger_daily_drawdown_pause(
    *,
    drawdown: float | None,
    daily_drawdown_limit: float,
    already_paused: bool,
) -> bool:
    if drawdown is None:
        return False
    return bool(drawdown <= daily_drawdown_limit and not already_paused)


def is_loss_cooldown_active(
    cooldown_until_utc: datetime.datetime | None,
    now_utc: datetime.datetime,
) -> bool:
    if cooldown_until_utc is None:
        return False
    return now_utc < cooldown_until_utc


def get_entry_gate_block_reason(
    *,
    manual_entry_paused: bool,
    daily_drawdown_paused: bool,
    cooldown_active: bool,
) -> str | None:
    if manual_entry_paused:
        return "manual_pause"
    if daily_drawdown_paused:
        return "daily_drawdown_pause"
    if cooldown_active:
        return "loss_cooldown"
    return None


def compute_loss_cooldown_until(
    *,
    consecutive_losses: int,
    max_consecutive_losses: int,
    cooldown_candles: int,
    now_utc: datetime.datetime,
) -> datetime.datetime | None:
    if consecutive_losses < max_consecutive_losses:
        return None
    cooldown_hours = cooldown_candles * 4
    return now_utc + datetime.timedelta(hours=cooldown_hours)

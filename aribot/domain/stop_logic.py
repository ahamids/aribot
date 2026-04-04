from __future__ import annotations


def should_close_for_hard_stop(position) -> bool:
    """Immediate hard-stop decision after each price refresh."""
    return bool(position.should_close_for_loss())


def should_activate_trailing(position) -> bool:
    """Whether trailing stop should be activated now."""
    return bool(position.should_activate_trailing_stop())


def update_trailing_if_active(position) -> bool:
    """Update trailing level when active, returning whether level changed."""
    return bool(position.trailing_stop_active and position.update_trailing_stop())


def evaluate_exit_reason(position, max_hold_minutes: int) -> str | None:
    """Evaluate non-hard-stop exits in current precedence order."""
    if position.should_close_for_trailing_stop():
        return "TRAILING_STOP"
    if position.should_close_for_stop_loss():
        return "SL_HIT"
    if position.should_close_for_time(max_hold_minutes):
        return "time_exit"
    return None

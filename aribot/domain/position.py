from __future__ import annotations

import datetime
from aribot.domain.pnl import derive_pnl_pct


class PaperPosition:
    """Represents a paper trading position with advanced management."""

    def __init__(self, symbol, side, entry_price, quantity, timestamp):
        self.symbol = symbol
        self.side = side
        self.entry_price = entry_price
        self.quantity = quantity
        self.timestamp = timestamp
        self.stop_loss = None
        self.trailing_stop_level = None
        self.current_price = entry_price
        self.gross_pnl = 0.0
        self.fee_cost = 0.0
        self.pnl = 0.0
        self.pnl_percentage = 0.0
        self.round_trip_fee_rate = 0.0011

        self.peak_pnl_percentage = 0.0

        self.profit_taking_levels = [0.02, 0.03, 0.05]
        self.profit_taking_sizes = [0.25, 0.25, 0.25]
        self.partial_exits = []

        self.trailing_stop_buffer = 0.015
        self.trailing_stop_active = False
        self.trailing_stop_trigger = 0.02

        self.native_sl_active = False
        self.native_tp_active = False
        self.native_trail_active = False
        self.native_sl_price = None
        self.native_stops_cancelled_at = None

    def update_price(self, current_price):
        self.current_price = current_price
        if self.side == "long":
            self.gross_pnl = (current_price - self.entry_price) * self.quantity
        else:
            self.gross_pnl = (self.entry_price - current_price) * self.quantity

        avg_notional = ((self.entry_price + current_price) / 2.0) * self.quantity
        self.fee_cost = avg_notional * self.round_trip_fee_rate
        self.pnl = self.gross_pnl - self.fee_cost
        self.pnl_percentage = derive_pnl_pct(self.entry_price, self.current_price, self.side)

        if self.pnl_percentage > self.peak_pnl_percentage:
            self.peak_pnl_percentage = self.pnl_percentage

    def should_close_for_loss(self):
        return self.pnl_percentage <= -2.5

    def should_close_for_stop_loss(self):
        if self.stop_loss is None:
            return False

        if self.side == "long":
            return self.current_price <= self.stop_loss
        return self.current_price >= self.stop_loss

    def should_activate_trailing_stop(self):
        return self.pnl_percentage >= (self.trailing_stop_trigger * 100) and not self.trailing_stop_active

    def activate_trailing_stop(self):
        self.trailing_stop_active = True
        self.update_trailing_stop()

    def update_trailing_stop(self):
        if not self.trailing_stop_active:
            return False

        if self.side == "long":
            highest_price = self.entry_price * (1 + self.peak_pnl_percentage / 100)
            level = highest_price * (1 - self.trailing_stop_buffer)
            if self.trailing_stop_level is None or level > self.trailing_stop_level:
                self.trailing_stop_level = level
                return True
        else:
            lowest_price = self.entry_price * (1 - self.peak_pnl_percentage / 100)
            level = lowest_price * (1 + self.trailing_stop_buffer)
            if self.trailing_stop_level is None or level < self.trailing_stop_level:
                self.trailing_stop_level = level
                return True

        return False

    def should_close_for_trailing_stop(self):
        if not self.trailing_stop_active or self.trailing_stop_level is None:
            return False

        if self.side == "long":
            return self.current_price <= self.trailing_stop_level
        return self.current_price >= self.trailing_stop_level

    def should_take_partial_profit(self):
        for idx, level in enumerate(self.profit_taking_levels):
            already_taken = any(exit_data["level"] == level for exit_data in self.partial_exits)
            if not already_taken and self.pnl_percentage >= (level * 100):
                return idx, level
        return None

    def take_partial_profit(self, idx, level):
        size = self.profit_taking_sizes[idx]
        partial_pnl = self.pnl * size
        self.partial_exits.append({"level": level, "size": size, "pnl": partial_pnl, "time": datetime.datetime.now()})
        self.quantity *= (1 - size)
        return partial_pnl

    def age_minutes(self):
        timestamp = self.timestamp
        if isinstance(timestamp, datetime.datetime) and timestamp.tzinfo is not None:
            now_utc = datetime.datetime.now(datetime.timezone.utc)
            ts_utc = timestamp.astimezone(datetime.timezone.utc)
            return (now_utc - ts_utc).total_seconds() / 60.0
        return (datetime.datetime.now() - timestamp).total_seconds() / 60.0

    def should_close_for_time(self, max_minutes=1440):
        return self.age_minutes() >= max_minutes

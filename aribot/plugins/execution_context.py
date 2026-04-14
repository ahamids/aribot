from __future__ import annotations

import datetime
import time

from aribot.domain.stop_logic import evaluate_exit_reason
from aribot.domain.stop_logic import should_activate_trailing
from aribot.domain.stop_logic import should_close_for_hard_stop


class PluginExecutionContext:
    """Runtime facade that routes operations through selected plugins with safe fallbacks."""

    def __init__(self, bot, plugins):
        self.bot = bot
        self.plugins = plugins

    def trade_symbols(self) -> list[str]:
        configured = list(getattr(self.bot, "trade_symbols", []) or [])
        if configured:
            return configured

        exchange = getattr(self.plugins, "exchange", None)
        if exchange is not None and hasattr(exchange, "list_symbols"):
            try:
                symbols = exchange.list_symbols()
                if isinstance(symbols, list) and symbols:
                    return symbols
            except Exception:
                pass
        return list(getattr(self.bot, "quote_swaps", []))

    def regime_signal(self):
        regime = getattr(self.plugins, "regime_filter", None)
        if regime is not None and hasattr(regime, "update"):
            try:
                return regime.update()
            except Exception:
                return None
        return self.bot.fetch_btc_regime_signal()

    def analyze_symbol(self, symbol: str, for_entry: bool = False):
        strategy = getattr(self.plugins, "strategy", None)
        if strategy is not None and hasattr(strategy, "analyze_symbol"):
            try:
                return strategy.analyze_symbol(symbol, for_entry=for_entry)
            except Exception:
                return None
        return self.bot.analyze_market(symbol, for_entry=for_entry)

    def refresh_risk_breakers(self) -> None:
        risk = getattr(self.plugins, "risk", None)
        if risk is not None and hasattr(risk, "refresh_daily_breakers"):
            try:
                risk.refresh_daily_breakers()
                return
            except Exception:
                pass
        self.bot.update_daily_drawdown_pause()

    def entry_gate_reason(self, now_utc=None):
        risk = getattr(self.plugins, "risk", None)
        if risk is not None and hasattr(risk, "entry_gate_block_reason"):
            try:
                return risk.entry_gate_block_reason(now_utc=now_utc)
            except Exception:
                return self.bot.entry_gate_block_reason(now_utc=now_utc)
        return self.bot.entry_gate_block_reason(now_utc=now_utc)

    def fetch_ticker(self, symbol: str):
        exchange = getattr(self.plugins, "exchange", None)
        if exchange is not None and hasattr(exchange, "fetch_ticker"):
            try:
                return exchange.fetch_ticker(symbol)
            except Exception:
                return self.bot.exchange.fetch_ticker(symbol)
        return self.bot.exchange.fetch_ticker(symbol)

    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int = 100):
        exchange = getattr(self.plugins, "exchange", None)
        if exchange is not None and hasattr(exchange, "fetch_ohlcv"):
            try:
                return exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
            except Exception:
                return self.bot.exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
        return self.bot.exchange.fetch_ohlcv(symbol, timeframe, limit=limit)

    def fetch_balance(self):
        exchange = getattr(self.plugins, "exchange", None)
        if exchange is not None and hasattr(exchange, "fetch_balance"):
            try:
                return exchange.fetch_balance()
            except Exception:
                return self.bot.exchange.fetch_balance()
        return self.bot.exchange.fetch_balance()

    def set_native_initial_protection(self, symbol: str, side: str, entry_price: float, quantity: float):
        if not getattr(self.bot, "live_execution_enabled", False) or getattr(self.bot, "order_executor", None) is None:
            return None
        return self.bot.order_executor.set_native_initial_protection(
            symbol=symbol,
            side=side,
            entry_price=entry_price,
            quantity=quantity,
        )

    def set_native_trailing(self, symbol: str):
        if not getattr(self.bot, "live_execution_enabled", False) or getattr(self.bot, "order_executor", None) is None:
            return None
        return self.bot.order_executor.set_native_trailing(symbol)

    def clear_native_protection(self, symbol: str):
        if not getattr(self.bot, "live_execution_enabled", False) or getattr(self.bot, "order_executor", None) is None:
            return None

        cancel_method = getattr(self.bot.order_executor, "cancel_all_native_stops", None)
        if not callable(cancel_method):
            cancel_method = getattr(self.bot.order_executor, "clear_native_protection", None)

        if callable(cancel_method):
            return cancel_method(symbol)

        return {
            "ok": False,
            "warnings": [{"operation": "cancel_all_native_stops", "error_type": "missing_method"}],
        }

    def finalize_position_close(self, symbol: str, pos, reason: str, exchange_already_closed: bool = False) -> bool:
        helper = getattr(self.bot, "_finalize_position_close", None)
        if not callable(helper):
            return False
        helper(
            symbol=symbol,
            pos=pos,
            reason=reason,
            exchange_already_closed=exchange_already_closed,
        )
        return True

    def handle_runtime_local_missing_on_exchange(self, symbol: str, reconstructed_close_price=None) -> bool:
        self.bot.logger.warning(
            f"⚠️ Runtime reconciliation detected local-only open position for {symbol}; "
            f"closing locally (exchange already flat)."
        )
        self.bot.emit_structured_event(
            'WARNING',
            'runtime_local_missing_on_exchange',
            'reconciliation',
            'Runtime reconciliation found local open position missing on exchange; local state was closed.',
            symbol=symbol,
            values={
                'reconstructed_close_price': reconstructed_close_price,
            },
        )
        self.bot.close_position(symbol, 'runtime_exchange_flat_reconciled', exchange_already_closed=True)
        return True

    def handle_runtime_quantity_mismatch(
        self,
        symbol: str,
        pos,
        *,
        local_qty: float,
        exchange_qty: float,
        qty_diff_pct: float,
        exchange_entry: float,
        exchange_side: str,
    ) -> bool:
        self.bot.logger.warning(
            f"⚠️ Runtime reconciliation quantity mismatch for {symbol}: "
            f"local={local_qty:.8f}, exchange={exchange_qty:.8f}. Updating local state to exchange truth."
        )
        pos.quantity = exchange_qty
        if exchange_entry > 0.0:
            pos.entry_price = exchange_entry
        if exchange_side in {'long', 'short'}:
            pos.side = exchange_side
        self.bot.persist_position(pos)
        self.bot.emit_structured_event(
            'WARNING',
            'runtime_position_mismatch_exchange_truth',
            'reconciliation',
            'Runtime reconciliation updated local position values to exchange truth.',
            symbol=symbol,
            values={
                'local_quantity_before': local_qty,
                'exchange_quantity': exchange_qty,
                'qty_diff_pct': qty_diff_pct,
                'exchange_entry_price': exchange_entry if exchange_entry > 0.0 else None,
                'exchange_side': exchange_side,
            },
        )
        return True

    def handle_trailing_activation(self, symbol: str, pos) -> bool:
        pos.activate_trailing_stop()
        self.bot.logger.info(f"🎯 TRAILING ACTIVATED {symbol} level={pos.trailing_stop_level:.8f}")
        self.bot._apply_native_trailing_protection(pos)
        self.bot.persist_position(pos)
        return True

    def handle_partial_profit(self, symbol: str, pos, idx: int, level: float, to_close: list):
        helper = getattr(self.bot, "_handle_partial_profit", None)
        if not callable(helper):
            return None
        skip_symbol = bool(helper(symbol, pos, idx, level, to_close))
        return {"handled": True, "skip_symbol": skip_symbol}

    def handle_trailing_update(self, symbol: str, pos) -> bool:
        if not (pos.trailing_stop_active and pos.update_trailing_stop()):
            return False
        self.bot.logger.info(f"📈 TRAIL UPDATED {symbol} level={pos.trailing_stop_level:.8f}")
        self.bot.persist_position(pos)
        return True

    def determine_exit_reason(self, pos, max_hold_minutes: int):
        return evaluate_exit_reason(pos, max_hold_minutes)

    def should_close_for_hard_stop(self, pos) -> bool:
        return bool(should_close_for_hard_stop(pos))

    def should_activate_trailing(self, pos) -> bool:
        return bool(should_activate_trailing(pos))

    def close_queued_positions(self, to_close: list[tuple[str, str]]) -> int:
        closed = 0
        for symbol, reason in to_close:
            self.bot.close_position(symbol, reason)
            closed += 1
        return closed

    def scan_entries_window(self, cycle: int) -> int:
        signals = 0

        if cycle == 1 and not self.bot.is_signal_window():
            self.bot.logger.info('🚦 Cycle 1 bootstrap: evaluating new entry signals outside 4H window')
        else:
            self.bot.logger.info('🕓 4H close window active: evaluating new entry signals')

        regime_signal = self.regime_signal()
        self.bot.last_regime_signal = regime_signal or 'UNAVAILABLE'
        if regime_signal is None:
            self.bot.logger.warning('⚠️ BTC regime unavailable; skipping new entries this window')
            return signals

        self.bot.logger.info(f'📈 BTC regime gate active: {regime_signal}-only entries')
        for symbol in self.trade_symbols():
            gate_reason = self.entry_gate_reason(now_utc=datetime.datetime.now(datetime.timezone.utc))
            if gate_reason == 'manual_pause':
                self.bot.logger.info('⏸️ Manual pause active: skipping new entries')
                break
            if gate_reason == 'daily_drawdown_pause':
                self.bot.logger.info('🛑 Daily drawdown pause active: skipping new entries')
                break
            if gate_reason == 'loss_cooldown':
                self.bot.logger.info(f"⏸️ Loss cooldown active until {self.bot.cooldown_until_utc.isoformat()}: skipping new entries")
                break
            if len(self.bot.positions) >= self.bot.max_open_positions:
                self.bot.logger.info(f"⛔ Position cap reached ({self.bot.max_open_positions}); stopping signal scan")
                break

            anal = self.analyze_symbol(symbol, for_entry=True)
            if anal and anal.get('confirmed'):
                if anal.get('signal') != regime_signal:
                    continue
                if self.bot.open_position(anal):
                    signals += 1
            time.sleep(0.05)

        return signals

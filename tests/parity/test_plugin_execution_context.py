import unittest

from aribot.plugins.execution_context import PluginExecutionContext


class _DummyExchange:
    def fetch_ticker(self, symbol):
        return {"symbol": symbol, "last": 1.0}

    def fetch_ohlcv(self, symbol, timeframe, limit=100):
        return [[0, 1, 1, 1, 1, 1]] * limit


class _DummyBot:
    def __init__(self):
        self.quote_swaps = ["BTC/USDT:USDT"]
        self.exchange = _DummyExchange()
        self.live_execution_enabled = False
        self.order_executor = None
        self.positions = {}
        self.max_open_positions = 10
        self.cooldown_until_utc = None
        self.last_regime_signal = "UNKNOWN"
        self.finalized_closes = []
        self.close_calls = []
        self.emitted_events = []
        self.persisted_positions = []
        self.trailing_apply_calls = []
        self.partial_calls = []
        self.partial_helper_return = False

        class _Logger:
            def info(self, *_args, **_kwargs):
                return None

            def warning(self, *_args, **_kwargs):
                return None

        self.logger = _Logger()

    def fetch_btc_regime_signal(self):
        return "SELL"

    def is_signal_window(self):
        return True

    def analyze_market(self, symbol, for_entry=False):
        return {"symbol": symbol, "confirmed": bool(for_entry)}

    def update_daily_drawdown_pause(self):
        self.updated = True

    def entry_gate_block_reason(self, now_utc=None):
        return "daily_drawdown_pause"

    def open_position(self, _analysis):
        return False

    def _finalize_position_close(self, symbol, pos, reason, exchange_already_closed=False):
        self.finalized_closes.append((symbol, reason, bool(exchange_already_closed), pos))

    def close_position(self, symbol, reason, exchange_already_closed=False):
        self.close_calls.append((symbol, reason, bool(exchange_already_closed)))

    def emit_structured_event(self, level, event, category, message, symbol=None, values=None):
        self.emitted_events.append((level, event, category, message, symbol, values))

    def persist_position(self, pos):
        self.persisted_positions.append(pos)

    def _apply_native_trailing_protection(self, pos):
        self.trailing_apply_calls.append(pos)

    def _handle_partial_profit(self, symbol, pos, idx, level, to_close):
        self.partial_calls.append((symbol, pos, idx, level, to_close))
        return self.partial_helper_return


class _Plugins:
    class Exchange:
        def list_symbols(self):
            return ["PLUGIN/SYM"]

        def fetch_ticker(self, symbol):
            return {"symbol": symbol, "src": "plugin"}

        def fetch_ohlcv(self, symbol, timeframe, limit=100):
            return [[1, 1, 1, 1, 1, 1]] * limit

    class Strategy:
        def analyze_symbol(self, symbol, for_entry=False):
            return {"symbol": symbol, "confirmed": True, "signal": "BUY", "src": "plugin"}

    class Regime:
        def update(self):
            return "BUY"

    class Risk:
        def entry_gate_block_reason(self, now_utc=None):
            return None

        def refresh_daily_breakers(self):
            self.called = True

    exchange = Exchange()
    strategy = Strategy()
    regime_filter = Regime()
    risk = Risk()


class ExecutionContextTests(unittest.TestCase):
    def test_plugin_routes(self):
        ctx = PluginExecutionContext(_DummyBot(), _Plugins())
        self.assertEqual(ctx.trade_symbols(), ["PLUGIN/SYM"])
        self.assertEqual(ctx.regime_signal(), "BUY")
        self.assertEqual(ctx.entry_gate_reason(), None)
        self.assertEqual(ctx.analyze_symbol("X", for_entry=True)["src"], "plugin")
        self.assertEqual(ctx.fetch_ticker("Y")["src"], "plugin")
        self.assertEqual(len(ctx.fetch_ohlcv("Y", "4h", limit=3)), 3)

    def test_fallback_routes(self):
        bot = _DummyBot()
        class EmptyPlugins:
            pass

        ctx = PluginExecutionContext(bot, EmptyPlugins())
        self.assertEqual(ctx.trade_symbols(), ["BTC/USDT:USDT"])
        self.assertEqual(ctx.regime_signal(), "SELL")
        self.assertEqual(ctx.entry_gate_reason(), "daily_drawdown_pause")
        self.assertTrue(ctx.analyze_symbol("X", for_entry=True)["confirmed"])
        self.assertEqual(ctx.fetch_ticker("Y")["symbol"], "Y")
        self.assertEqual(len(ctx.fetch_ohlcv("Y", "4h", limit=2)), 2)

    def test_scan_entries_window_counts_opened_positions(self):
        bot = _DummyBot()

        def _open_position(_analysis):
            return True

        bot.open_position = _open_position
        ctx = PluginExecutionContext(bot, _Plugins())
        signals = ctx.scan_entries_window(cycle=1)
        self.assertEqual(signals, 1)

    def test_scan_entries_window_respects_gate_block(self):
        bot = _DummyBot()

        class _BlockedRisk:
            def entry_gate_block_reason(self, now_utc=None):
                return "manual_pause"

            def refresh_daily_breakers(self):
                return None

        class _BlockedPlugins(_Plugins):
            risk = _BlockedRisk()

        ctx = PluginExecutionContext(bot, _BlockedPlugins())
        self.assertEqual(ctx.scan_entries_window(cycle=1), 0)

    def test_native_protection_routes_through_executor(self):
        bot = _DummyBot()
        bot.live_execution_enabled = True

        class _Executor:
            def __init__(self):
                self.calls = []

            def set_native_initial_protection(self, symbol, side, entry_price, quantity):
                self.calls.append(("initial", symbol, side, entry_price, quantity))
                return {
                    "ok": True,
                    "native_sl_active": True,
                    "native_tp_active": True,
                    "native_trail_active": False,
                    "native_sl_price": 97.5,
                }

            def set_native_trailing(self, symbol):
                self.calls.append(("trailing", symbol))
                return {"ok": True}

            def cancel_all_native_stops(self, symbol):
                self.calls.append(("clear", symbol))
                return {"ok": True}

        bot.order_executor = _Executor()
        ctx = PluginExecutionContext(bot, _Plugins())

        initial = ctx.set_native_initial_protection("BTC/USDT:USDT", "long", 100.0, 1.0)
        trailing = ctx.set_native_trailing("BTC/USDT:USDT")
        cleared = ctx.clear_native_protection("BTC/USDT:USDT")

        self.assertTrue(initial["ok"])
        self.assertTrue(trailing["ok"])
        self.assertTrue(cleared["ok"])
        self.assertEqual(bot.order_executor.calls[0][0], "initial")
        self.assertEqual(bot.order_executor.calls[1][0], "trailing")
        self.assertEqual(bot.order_executor.calls[2][0], "clear")

    def test_native_protection_returns_none_when_unavailable(self):
        bot = _DummyBot()
        ctx = PluginExecutionContext(bot, _Plugins())
        self.assertIsNone(ctx.set_native_initial_protection("BTC/USDT:USDT", "long", 100.0, 1.0))
        self.assertIsNone(ctx.set_native_trailing("BTC/USDT:USDT"))
        self.assertIsNone(ctx.clear_native_protection("BTC/USDT:USDT"))

    def test_finalize_position_close_delegates_to_bot_helper(self):
        bot = _DummyBot()
        ctx = PluginExecutionContext(bot, _Plugins())
        marker = object()
        self.assertTrue(ctx.finalize_position_close("BTC/USDT:USDT", marker, "manual_test", True))
        self.assertEqual(len(bot.finalized_closes), 1)
        self.assertEqual(bot.finalized_closes[0][0], "BTC/USDT:USDT")
        self.assertEqual(bot.finalized_closes[0][1], "manual_test")
        self.assertTrue(bot.finalized_closes[0][2])
        self.assertIs(bot.finalized_closes[0][3], marker)

    def test_handle_runtime_local_missing_on_exchange_closes_position(self):
        bot = _DummyBot()
        ctx = PluginExecutionContext(bot, _Plugins())
        self.assertTrue(ctx.handle_runtime_local_missing_on_exchange("BTC/USDT:USDT", reconstructed_close_price=101.0))
        self.assertEqual(bot.close_calls, [("BTC/USDT:USDT", "runtime_exchange_flat_reconciled", True)])
        self.assertEqual(len(bot.emitted_events), 1)
        self.assertEqual(bot.emitted_events[0][1], "runtime_local_missing_on_exchange")

    def test_handle_runtime_quantity_mismatch_updates_position(self):
        bot = _DummyBot()
        ctx = PluginExecutionContext(bot, _Plugins())

        class _Pos:
            quantity = 1.0
            entry_price = 100.0
            side = "long"

        pos = _Pos()
        self.assertTrue(
            ctx.handle_runtime_quantity_mismatch(
                "BTC/USDT:USDT",
                pos,
                local_qty=1.0,
                exchange_qty=2.0,
                qty_diff_pct=50.0,
                exchange_entry=101.0,
                exchange_side="short",
            )
        )
        self.assertEqual(pos.quantity, 2.0)
        self.assertEqual(pos.entry_price, 101.0)
        self.assertEqual(pos.side, "short")
        self.assertEqual(len(bot.persisted_positions), 1)
        self.assertEqual(len(bot.emitted_events), 1)
        self.assertEqual(bot.emitted_events[0][1], "runtime_position_mismatch_exchange_truth")

    def test_handle_trailing_activation_applies_native_and_persists(self):
        bot = _DummyBot()
        ctx = PluginExecutionContext(bot, _Plugins())
        pos = type("P", (), {})()
        pos.trailing_stop_level = 100.0
        pos.activate_trailing_stop = lambda: setattr(pos, "trailing_stop_level", 101.0)

        self.assertTrue(ctx.handle_trailing_activation("BTC/USDT:USDT", pos))
        self.assertEqual(pos.trailing_stop_level, 101.0)
        self.assertEqual(len(bot.trailing_apply_calls), 1)
        self.assertEqual(len(bot.persisted_positions), 1)

    def test_handle_partial_profit_delegates_to_bot_helper(self):
        bot = _DummyBot()
        bot.partial_helper_return = True
        ctx = PluginExecutionContext(bot, _Plugins())
        marker_pos = object()
        to_close = []
        result = ctx.handle_partial_profit("BTC/USDT:USDT", marker_pos, 0, 0.02, to_close)
        self.assertEqual(result, {"handled": True, "skip_symbol": True})
        self.assertEqual(len(bot.partial_calls), 1)
        self.assertEqual(bot.partial_calls[0][0], "BTC/USDT:USDT")
        self.assertIs(bot.partial_calls[0][1], marker_pos)

    def test_handle_trailing_update_logs_and_persists_when_changed(self):
        bot = _DummyBot()
        ctx = PluginExecutionContext(bot, _Plugins())

        class _Pos:
            trailing_stop_active = True
            trailing_stop_level = 100.0

            def update_trailing_stop(self):
                self.trailing_stop_level = 101.0
                return True

        pos = _Pos()
        self.assertTrue(ctx.handle_trailing_update("BTC/USDT:USDT", pos))
        self.assertEqual(len(bot.persisted_positions), 1)

    def test_determine_exit_reason_uses_domain_logic(self):
        bot = _DummyBot()
        ctx = PluginExecutionContext(bot, _Plugins())
        class _Pos:
            trailing_stop_active = True
            trailing_stop_level = 101.0
            stop_loss = 90.0
            current_price = 100.0

            def should_close_for_trailing_stop(self):
                return True

            def should_close_for_stop_loss(self):
                return True

            def should_close_for_time(self, _max_hold_minutes):
                return False

        reason = ctx.determine_exit_reason(_Pos(), 999)
        self.assertEqual(reason, "TRAILING_STOP")

    def test_should_close_for_hard_stop_uses_domain_logic(self):
        bot = _DummyBot()
        ctx = PluginExecutionContext(bot, _Plugins())

        class _Pos:
            def should_close_for_loss(self):
                return True

        self.assertTrue(ctx.should_close_for_hard_stop(_Pos()))

    def test_should_activate_trailing_uses_domain_logic(self):
        bot = _DummyBot()
        ctx = PluginExecutionContext(bot, _Plugins())

        class _Pos:
            def should_activate_trailing_stop(self):
                return True

        self.assertTrue(ctx.should_activate_trailing(_Pos()))

    def test_close_queued_positions_closes_all(self):
        bot = _DummyBot()
        ctx = PluginExecutionContext(bot, _Plugins())
        closed = ctx.close_queued_positions([
            ("BTC/USDT:USDT", "stop_loss"),
            ("ETH/USDT:USDT", "time_exit"),
        ])
        self.assertEqual(closed, 2)
        self.assertEqual(bot.close_calls, [
            ("BTC/USDT:USDT", "stop_loss", False),
            ("ETH/USDT:USDT", "time_exit", False),
        ])


if __name__ == "__main__":
    unittest.main()

import datetime
import unittest

from aribot.runtime.engine import Aribot, PaperPosition, derive_pnl_pct
from aribot.domain.risk_gates import compute_drawdown
from aribot.domain.risk_gates import compute_loss_cooldown_until
from aribot.domain.risk_gates import get_entry_gate_block_reason
from aribot.domain.risk_gates import is_loss_cooldown_active
from aribot.domain.sizing import compute_entry_sizing
from aribot.domain.stop_logic import evaluate_exit_reason
from aribot.domain.stop_logic import should_close_for_hard_stop


class CharacterizationTests(unittest.TestCase):
    def _stub_bot(self):
        bot = Aribot.__new__(Aribot)
        bot.signal_boundary_window_seconds = 60
        bot.allow_missing_ticker_timestamp = True
        class _Logger:
            def info(self, *_args, **_kwargs):
                return None

            def warning(self, *_args, **_kwargs):
                return None
        bot.logger = _Logger()
        return bot

    def test_derive_pnl_pct_long_and_short(self):
        self.assertAlmostEqual(derive_pnl_pct(100, 110, "long"), 10.0)
        self.assertAlmostEqual(derive_pnl_pct(100, 90, "short"), 10.0)

    def test_derive_pnl_pct_invalid_input(self):
        self.assertEqual(derive_pnl_pct("bad", 100, "long"), 0.0)
        self.assertEqual(derive_pnl_pct(0, 100, "long"), 0.0)
        self.assertEqual(derive_pnl_pct(100, 100, "unknown"), 0.0)

    def test_signal_window_boundary(self):
        bot = self._stub_bot()
        active = datetime.datetime(2026, 1, 1, 0, 0, 10, tzinfo=datetime.timezone.utc)
        inactive_minute = datetime.datetime(2026, 1, 1, 0, 1, 0, tzinfo=datetime.timezone.utc)
        inactive_hour = datetime.datetime(2026, 1, 1, 1, 0, 10, tzinfo=datetime.timezone.utc)

        self.assertTrue(bot.is_signal_window(active))
        self.assertFalse(bot.is_signal_window(inactive_minute))
        self.assertFalse(bot.is_signal_window(inactive_hour))

    def test_calculate_wma_with_offset(self):
        bot = self._stub_bot()
        source = [1, 2, 3, 4, 5, 6, 7]
        wma = bot.calculate_wma(source, period=3, offset=2)
        # With offset=2, prices_for_wma becomes [1,2,3,4,5], so WMA over [3,4,5]
        expected = (3 * 1 + 4 * 2 + 5 * 3) / (1 + 2 + 3)
        self.assertAlmostEqual(wma, expected)

    def test_calculate_ohlc4(self):
        bot = self._stub_bot()
        ohlcv = [
            [0, 10.0, 14.0, 8.0, 12.0, 100],
            [1, 12.0, 16.0, 10.0, 14.0, 100],
        ]
        self.assertEqual(bot.calculate_ohlc4(ohlcv), [11.0, 13.0])

    def test_confirm_signal_buy(self):
        bot = self._stub_bot()
        # prior index = 2, breakout close must exceed close at highest-high candle in consec run
        ohlcv = [
            [0, 0, 10, 1, 9, 0],
            [1, 0, 30, 1, 10, 0],
            [2, 0, 20, 1, 11, 0],
            [3, 0, 25, 1, 12, 0],
        ]
        ohlc4 = [11, 12, 13, 14]
        wma = [10, 11, 12, 13]
        self.assertTrue(bot.confirm_signal(ohlcv, ohlc4, wma, 3, "BUY"))

    def test_confirm_signal_sell(self):
        bot = self._stub_bot()
        # prior index = 2, breakdown close must be lower than close at lowest-low candle in consec run
        ohlcv = [
            [0, 0, 30, 10, 20, 0],
            [1, 0, 30, 5, 19, 0],
            [2, 0, 30, 15, 18, 0],
            [3, 0, 30, 12, 17, 0],
        ]
        ohlc4 = [8, 7, 6, 5]
        wma = [9, 8, 7, 6]
        self.assertTrue(bot.confirm_signal(ohlcv, ohlc4, wma, 3, "SELL"))

    def test_partial_profit_defaults(self):
        pos = PaperPosition("BTC/USDT:USDT", "long", 100.0, 1.0, datetime.datetime.now())
        self.assertEqual(pos.profit_taking_levels, [0.02, 0.03, 0.05])
        self.assertEqual(pos.profit_taking_sizes, [0.25, 0.25, 0.25])

    def test_trailing_stop_activation(self):
        pos = PaperPosition("BTC/USDT:USDT", "long", 100.0, 1.0, datetime.datetime.now())
        pos.update_price(103.0)
        self.assertTrue(pos.should_activate_trailing_stop())
        pos.activate_trailing_stop()
        self.assertTrue(pos.trailing_stop_active)
        self.assertIsNotNone(pos.trailing_stop_level)

    def test_extract_ticker_timestamp_fallback(self):
        bot = self._stub_bot()
        now_utc = datetime.datetime(2026, 1, 1, 0, 0, 0, tzinfo=datetime.timezone.utc)

        ts_ms, source, fallback = bot.extract_ticker_timestamp_ms(
            {"timestamp": None, "datetime": None, "info": {"updatedTime": "1704067200"}},
            now_utc,
        )
        self.assertEqual(ts_ms, 1704067200000)
        self.assertEqual(source, "ticker.info.updatedTime")
        self.assertFalse(fallback)

    def test_entry_sizing_formula_baseline(self):
        sizing = compute_entry_sizing(
            current_balance=400.0,
            entry_risk_pct=0.11,
            atr_ratio=0.02,
            atr_volatility_cutoff=0.05,
            atr_size_scalar=0.5,
            leverage=5.0,
            round_trip_fee_rate=0.0011,
            price=100.0,
        )

        expected_gross_notional = 400.0 * 0.11 * 5.0
        expected_net_notional = expected_gross_notional * (1 - 0.0011)
        self.assertAlmostEqual(sizing["risk_pct"], 0.11)
        self.assertAlmostEqual(sizing["gross_notional"], expected_gross_notional)
        self.assertAlmostEqual(sizing["net_notional"], expected_net_notional)
        self.assertAlmostEqual(sizing["gross_qty"], expected_gross_notional / 100.0)
        self.assertAlmostEqual(sizing["net_qty"], expected_net_notional / 100.0)

    def test_entry_sizing_atr_scalar_applied(self):
        sizing = compute_entry_sizing(
            current_balance=400.0,
            entry_risk_pct=0.11,
            atr_ratio=0.06,
            atr_volatility_cutoff=0.05,
            atr_size_scalar=0.5,
            leverage=5.0,
            round_trip_fee_rate=0.0011,
            price=100.0,
        )

        self.assertAlmostEqual(sizing["risk_pct"], 0.055)

    def test_stop_logic_hard_stop_wrapper(self):
        pos = PaperPosition("BTC/USDT:USDT", "long", 100.0, 1.0, datetime.datetime.now())
        pos.update_price(97.0)
        self.assertTrue(should_close_for_hard_stop(pos))

    def test_stop_logic_exit_precedence(self):
        pos = PaperPosition("BTC/USDT:USDT", "long", 100.0, 1.0, datetime.datetime.now())
        pos.trailing_stop_active = True
        pos.trailing_stop_level = 101.0
        pos.stop_loss = 90.0
        pos.current_price = 100.0
        # Both trailing and stop-loss conditions are true, trailing must win.
        self.assertEqual(evaluate_exit_reason(pos, max_hold_minutes=10_000), "TRAILING_STOP")

    def test_stop_logic_time_exit(self):
        old_ts = datetime.datetime.now() - datetime.timedelta(hours=41)
        pos = PaperPosition("BTC/USDT:USDT", "long", 100.0, 1.0, old_ts)
        self.assertEqual(evaluate_exit_reason(pos, max_hold_minutes=40 * 60), "time_exit")

    def test_risk_gate_drawdown_compute(self):
        drawdown = compute_drawdown(current_balance=950.0, session_start_balance=1000.0)
        self.assertAlmostEqual(drawdown, -0.05)
        self.assertIsNone(compute_drawdown(current_balance=100.0, session_start_balance=0.0))

    def test_risk_gate_reason_precedence(self):
        self.assertEqual(
            get_entry_gate_block_reason(
                manual_entry_paused=True,
                daily_drawdown_paused=True,
                cooldown_active=True,
            ),
            "manual_pause",
        )
        self.assertEqual(
            get_entry_gate_block_reason(
                manual_entry_paused=False,
                daily_drawdown_paused=True,
                cooldown_active=True,
            ),
            "daily_drawdown_pause",
        )
        self.assertEqual(
            get_entry_gate_block_reason(
                manual_entry_paused=False,
                daily_drawdown_paused=False,
                cooldown_active=True,
            ),
            "loss_cooldown",
        )

    def test_risk_gate_cooldown_helpers(self):
        now_utc = datetime.datetime(2026, 1, 1, 0, 0, 0, tzinfo=datetime.timezone.utc)
        cooldown_until = compute_loss_cooldown_until(
            consecutive_losses=3,
            max_consecutive_losses=3,
            cooldown_candles=2,
            now_utc=now_utc,
        )
        self.assertIsNotNone(cooldown_until)
        self.assertTrue(is_loss_cooldown_active(cooldown_until, now_utc + datetime.timedelta(hours=1)))
        self.assertFalse(is_loss_cooldown_active(cooldown_until, now_utc + datetime.timedelta(hours=9)))

    def test_plugin_symbol_list_delegation(self):
        bot = self._stub_bot()
        bot.quote_swaps = ["FALLBACK"]

        class _ExchangePlugin:
            def list_symbols(self):
                return ["PLUGIN"]

        class _Plugins:
            exchange = _ExchangePlugin()

        bot.runtime_plugins = _Plugins()
        self.assertEqual(bot.get_trade_symbols(), ["PLUGIN"])

    def test_plugin_regime_signal_delegation(self):
        bot = self._stub_bot()

        class _RegimePlugin:
            def update(self):
                return "BUY"

        class _Plugins:
            regime_filter = _RegimePlugin()

        bot.runtime_plugins = _Plugins()
        self.assertEqual(bot.get_regime_signal(), "BUY")

    def test_plugin_risk_gate_delegation(self):
        bot = self._stub_bot()

        class _RiskPlugin:
            def entry_gate_block_reason(self, now_utc=None):
                return "manual_pause"

        class _Plugins:
            risk = _RiskPlugin()

        bot.runtime_plugins = _Plugins()
        self.assertEqual(bot.get_entry_gate_reason(), "manual_pause")

    def test_plugin_strategy_delegation(self):
        bot = self._stub_bot()

        class _StrategyPlugin:
            def analyze_symbol(self, symbol, for_entry=False):
                return {"symbol": symbol, "confirmed": bool(for_entry)}

        class _Plugins:
            strategy = _StrategyPlugin()

        bot.runtime_plugins = _Plugins()
        out = bot.analyze_symbol("BTC/USDT:USDT", for_entry=True)
        self.assertEqual(out["symbol"], "BTC/USDT:USDT")
        self.assertTrue(out["confirmed"])

    def test_resolve_btc_regime_symbol_uses_market_quote(self):
        bot = self._stub_bot()
        bot.market_quote = "USDC"
        bot.markets = {
            "BTC/USDT:USDT": {"type": "swap", "base": "BTC", "quote": "USDT"},
            "BTC/USDC:USDC": {"type": "swap", "base": "BTC", "quote": "USDC"},
        }
        self.assertEqual(bot.resolve_btc_regime_symbol(), "BTC/USDC:USDC")

    def test_fetch_exchange_quote_balance_uses_market_quote_bucket(self):
        bot = self._stub_bot()
        bot.live_execution_enabled = True
        bot.market_quote = "USDC"

        class _Exchange:
            def fetch_balance(self):
                return {
                    "USDC": {"total": 321.5, "free": 320.0},
                    "total": {"USDC": 321.5},
                    "free": {"USDC": 320.0},
                }

        bot.exchange = _Exchange()

        self.assertEqual(bot.fetch_exchange_quote_balance(), 321.5)

    def test_fetch_exchange_quote_balance_delegates_runtime_context(self):
        bot = self._stub_bot()
        bot.live_execution_enabled = True
        bot.market_quote = "USDC"

        class _RuntimeContext:
            def fetch_balance(self):
                return {
                    "USDC": {"total": 111.0, "free": 109.0},
                    "total": {"USDC": 111.0},
                    "free": {"USDC": 109.0},
                }

        class _Exchange:
            def fetch_balance(self):
                raise RuntimeError("direct exchange path should not be used")

        bot.runtime_context = _RuntimeContext()
        bot.exchange = _Exchange()

        self.assertEqual(bot.fetch_exchange_quote_balance(), 111.0)

    def test_native_initial_protection_delegates_runtime_context(self):
        bot = self._stub_bot()
        bot.live_execution_enabled = True
        bot.order_executor = None
        persisted = []
        bot.persist_position = lambda p: persisted.append(p)

        class _RuntimeContext:
            def set_native_initial_protection(self, symbol, side, entry_price, quantity):
                return {
                    "ok": True,
                    "native_sl_active": True,
                    "native_tp_active": True,
                    "native_trail_active": False,
                    "native_sl_price": 97.5,
                }

        bot.runtime_context = _RuntimeContext()
        pos = PaperPosition("BTC/USDT:USDT", "long", 100.0, 1.0, datetime.datetime.now())

        bot._apply_native_initial_protection(pos)

        self.assertTrue(pos.native_sl_active)
        self.assertTrue(pos.native_tp_active)
        self.assertFalse(pos.native_trail_active)
        self.assertEqual(pos.native_sl_price, 97.5)
        self.assertEqual(len(persisted), 1)

    def test_close_position_delegates_finalize_to_runtime_context(self):
        bot = self._stub_bot()
        bot.live_execution_enabled = False
        bot.positions = {}

        pos = PaperPosition("BTC/USDT:USDT", "long", 100.0, 1.0, datetime.datetime.now())
        bot.positions[pos.symbol] = pos
        bot._clear_native_protection_on_close = lambda _pos: None

        class _RuntimeContext:
            def __init__(self):
                self.calls = []

            def finalize_position_close(self, symbol, pos, reason, exchange_already_closed=False):
                self.calls.append((symbol, reason, bool(exchange_already_closed), pos))
                return True

        ctx = _RuntimeContext()
        bot.runtime_context = ctx

        bot.close_position(pos.symbol, "manual_test", exchange_already_closed=True)

        self.assertEqual(len(ctx.calls), 1)
        self.assertEqual(ctx.calls[0][0], "BTC/USDT:USDT")
        self.assertEqual(ctx.calls[0][1], "manual_test")
        self.assertTrue(ctx.calls[0][2])

    def test_runtime_reconcile_local_missing_delegates_to_runtime_context(self):
        bot = self._stub_bot()
        bot.live_execution_enabled = True
        symbol = "BTC/USDT:USDT"
        pos = PaperPosition(symbol, "long", 100.0, 1.0, datetime.datetime.now())
        bot.positions = {symbol: pos}

        class _StartupReconciler:
            def fetch_open_exchange_positions(self):
                return {}

            def reconstruct_close_from_trades(self, symbol, side, open_quantity):
                return None

        class _RuntimeContext:
            def __init__(self):
                self.calls = []

            def handle_runtime_local_missing_on_exchange(self, symbol, reconstructed_close_price=None):
                self.calls.append((symbol, reconstructed_close_price))
                return True

        bot.startup_reconciler = _StartupReconciler()
        ctx = _RuntimeContext()
        bot.runtime_context = ctx

        bot.reconcile_runtime_positions_with_exchange()

        self.assertEqual(len(ctx.calls), 1)
        self.assertEqual(ctx.calls[0][0], symbol)

    def test_runtime_reconcile_quantity_mismatch_delegates_to_runtime_context(self):
        bot = self._stub_bot()
        bot.live_execution_enabled = True
        symbol = "BTC/USDT:USDT"
        pos = PaperPosition(symbol, "long", 100.0, 1.0, datetime.datetime.now())
        bot.positions = {symbol: pos}

        class _StartupReconciler:
            def fetch_open_exchange_positions(self):
                return {
                    symbol: {
                        "quantity": 2.0,
                        "entry_price": 101.0,
                        "side": "Sell",
                    }
                }

            def reconstruct_close_from_trades(self, symbol, side, open_quantity):
                return None

        class _RuntimeContext:
            def __init__(self):
                self.calls = []

            def handle_runtime_quantity_mismatch(
                self,
                symbol,
                pos,
                *,
                local_qty,
                exchange_qty,
                qty_diff_pct,
                exchange_entry,
                exchange_side,
            ):
                self.calls.append(
                    {
                        "symbol": symbol,
                        "local_qty": local_qty,
                        "exchange_qty": exchange_qty,
                        "exchange_entry": exchange_entry,
                        "exchange_side": exchange_side,
                    }
                )
                return True

        bot.startup_reconciler = _StartupReconciler()
        ctx = _RuntimeContext()
        bot.runtime_context = ctx

        bot.reconcile_runtime_positions_with_exchange()

        self.assertEqual(len(ctx.calls), 1)
        self.assertEqual(ctx.calls[0]["symbol"], symbol)
        self.assertEqual(ctx.calls[0]["local_qty"], 1.0)
        self.assertEqual(ctx.calls[0]["exchange_qty"], 2.0)
        self.assertEqual(ctx.calls[0]["exchange_entry"], 101.0)
        self.assertEqual(ctx.calls[0]["exchange_side"], "short")

    def test_update_positions_trailing_activation_delegates_to_runtime_context(self):
        bot = self._stub_bot()
        symbol = "BTC/USDT:USDT"
        pos = PaperPosition(symbol, "long", 100.0, 1.0, datetime.datetime.now())
        pos.profit_taking_levels = [0.20, 0.30, 0.50]
        pos.profit_taking_sizes = [0.25, 0.25, 0.25]

        bot.positions = {symbol: pos}
        bot.live_execution_enabled = False
        bot.max_hold_minutes = 10_000
        bot.analyze_market = lambda _symbol, for_entry=False: {"current_price": 103.0}
        bot.persist_position = lambda _pos: None
        bot.record_partial_realization = lambda *_args, **_kwargs: None
        bot.persist_runtime_state = lambda: None
        bot.emit_structured_event = lambda *_args, **_kwargs: None
        bot._apply_native_trailing_protection = lambda _pos: None
        bot.close_position = lambda _symbol, _reason: None
        bot.current_balance = 0.0
        bot.total_pnl = 0.0

        class _RuntimeContext:
            def __init__(self):
                self.calls = []

            def handle_trailing_activation(self, symbol, pos):
                self.calls.append((symbol, pos))
                pos.activate_trailing_stop()
                return True

        ctx = _RuntimeContext()
        bot.runtime_context = ctx

        bot.update_positions()

        self.assertEqual(len(ctx.calls), 1)
        self.assertEqual(ctx.calls[0][0], symbol)
        self.assertTrue(pos.trailing_stop_active)

    def test_update_positions_partial_profit_delegates_to_runtime_context(self):
        bot = self._stub_bot()
        symbol = "BTC/USDT:USDT"
        pos = PaperPosition(symbol, "long", 100.0, 1.0, datetime.datetime.now())
        pos.profit_taking_levels = [0.02, 0.03, 0.05]
        pos.profit_taking_sizes = [0.25, 0.25, 0.25]

        bot.positions = {symbol: pos}
        bot.live_execution_enabled = False
        bot.max_hold_minutes = 10_000
        bot.analyze_market = lambda _symbol, for_entry=False: {"current_price": 103.0}
        bot.persist_position = lambda _pos: None
        bot.record_partial_realization = lambda *_args, **_kwargs: None
        bot.persist_runtime_state = lambda: None
        bot.emit_structured_event = lambda *_args, **_kwargs: None
        bot._apply_native_trailing_protection = lambda _pos: None
        bot.close_position = lambda _symbol, _reason: None
        bot.current_balance = 0.0
        bot.total_pnl = 0.0

        class _RuntimeContext:
            def __init__(self):
                self.calls = []

            def handle_partial_profit(self, symbol, pos, idx, level, to_close):
                self.calls.append((symbol, idx, level))
                return {"handled": True, "skip_symbol": True}

        ctx = _RuntimeContext()
        bot.runtime_context = ctx

        bot.update_positions()

        self.assertEqual(len(ctx.calls), 1)
        self.assertEqual(ctx.calls[0][0], symbol)

    def test_update_positions_analysis_delegates_to_runtime_context(self):
        bot = self._stub_bot()
        symbol = "BTC/USDT:USDT"
        pos = PaperPosition(symbol, "long", 100.0, 1.0, datetime.datetime.now())
        pos.profit_taking_levels = [0.20, 0.30, 0.50]
        pos.profit_taking_sizes = [0.25, 0.25, 0.25]

        bot.positions = {symbol: pos}
        bot.live_execution_enabled = False
        bot.max_hold_minutes = 10_000

        def _analyze_market_should_not_run(_symbol, for_entry=False):
            raise AssertionError("analyze_market should not be used when runtime context provides analysis")

        bot.analyze_market = _analyze_market_should_not_run
        bot.persist_position = lambda _pos: None
        bot.record_partial_realization = lambda *_args, **_kwargs: None
        bot.persist_runtime_state = lambda: None
        bot.emit_structured_event = lambda *_args, **_kwargs: None
        bot._apply_native_trailing_protection = lambda _pos: None
        bot.close_position = lambda _symbol, _reason: None
        bot.current_balance = 0.0
        bot.total_pnl = 0.0

        class _RuntimeContext:
            def __init__(self):
                self.analysis_calls = []

            def analyze_symbol(self, symbol, for_entry=False):
                self.analysis_calls.append((symbol, for_entry))
                return {"current_price": 103.0}

        ctx = _RuntimeContext()
        bot.runtime_context = ctx

        bot.update_positions()

        self.assertEqual(len(ctx.analysis_calls), 1)
        self.assertEqual(ctx.analysis_calls[0], (symbol, False))

    def test_update_positions_hard_stop_can_delegate_to_runtime_context(self):
        bot = self._stub_bot()
        symbol = "BTC/USDT:USDT"
        pos = PaperPosition(symbol, "long", 100.0, 1.0, datetime.datetime.now())
        pos.stop_loss = 80.0

        bot.positions = {symbol: pos}
        bot.live_execution_enabled = False
        bot.max_hold_minutes = 10_000
        bot.analyze_market = lambda _symbol, for_entry=False: {"current_price": 101.0}
        bot.persist_position = lambda _pos: None
        bot.record_partial_realization = lambda *_args, **_kwargs: None
        bot.persist_runtime_state = lambda: None
        bot.emit_structured_event = lambda *_args, **_kwargs: None
        bot._apply_native_trailing_protection = lambda _pos: None
        bot.current_balance = 0.0
        bot.total_pnl = 0.0

        closed = []
        bot.close_position = lambda _symbol, _reason: closed.append((_symbol, _reason))

        class _RuntimeContext:
            def should_close_for_hard_stop(self, _pos):
                return True

            def analyze_symbol(self, symbol, for_entry=False):
                return {"current_price": 101.0}

        bot.runtime_context = _RuntimeContext()

        bot.update_positions()

        self.assertEqual(closed, [(symbol, 'stop_loss')])

    def test_update_positions_close_queue_can_delegate_to_runtime_context(self):
        bot = self._stub_bot()
        symbol = "BTC/USDT:USDT"
        pos = PaperPosition(symbol, "long", 100.0, 1.0, datetime.datetime.now())
        pos.stop_loss = 80.0

        bot.positions = {symbol: pos}
        bot.live_execution_enabled = False
        bot.max_hold_minutes = 10_000
        bot.analyze_market = lambda _symbol, for_entry=False: {"current_price": 101.0}
        bot.persist_position = lambda _pos: None
        bot.record_partial_realization = lambda *_args, **_kwargs: None
        bot.persist_runtime_state = lambda: None
        bot.emit_structured_event = lambda *_args, **_kwargs: None
        bot._apply_native_trailing_protection = lambda _pos: None
        bot.current_balance = 0.0
        bot.total_pnl = 0.0

        def _fallback_should_not_run(_symbol, _reason):
            raise AssertionError("fallback close_position should not run when runtime context handles close queue")

        bot.close_position = _fallback_should_not_run

        class _RuntimeContext:
            def __init__(self):
                self.closed = []

            def should_close_for_hard_stop(self, _pos):
                return True

            def analyze_symbol(self, _symbol, for_entry=False):
                return {"current_price": 101.0}

            def close_queued_positions(self, to_close):
                self.closed.extend(list(to_close))
                return len(to_close)

        ctx = _RuntimeContext()
        bot.runtime_context = ctx

        bot.update_positions()

        self.assertEqual(ctx.closed, [(symbol, 'stop_loss')])


if __name__ == "__main__":
    unittest.main()

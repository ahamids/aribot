import unittest

from aribot.plugins.factory import build_runtime_plugins
from aribot.plugins.registry import PluginSelection


class _DummyExchange:
    def fetch_ticker(self, _symbol):
        return {"last": 1.0, "symbol": _symbol}

    def fetch_ohlcv(self, _symbol, _timeframe, limit=100):
        return [[0, 1, 1, 1, 1, 1]] * limit


class _DummyBot:
    def __init__(self):
        self.quote_swaps = ["BTC/USDT:USDT"]
        self.exchange = _DummyExchange()
        self.last_regime_signal = "BUY"

    def analyze_market(self, symbol, for_entry=False):
        return {"symbol": symbol, "confirmed": bool(for_entry)}

    def fetch_btc_regime_signal(self):
        return "BUY"

    def entry_gate_block_reason(self):
        return None

    def update_daily_drawdown_pause(self):
        return None


class PluginFactoryTests(unittest.TestCase):
    def test_build_runtime_plugins_happy_path(self):
        selection = PluginSelection(
            exchange="bybit",
            strategy="wma45_ohlc4",
            regime_filter="wma_regime",
            risk="default_risk",
        )
        bot = _DummyBot()
        plugins = build_runtime_plugins(selection, bot)

        self.assertEqual(plugins.exchange.name(), "bybit")
        self.assertEqual(plugins.strategy.name(), "wma45_ohlc4")
        self.assertEqual(plugins.regime_filter.name(), "wma_regime")
        self.assertEqual(plugins.risk.name(), "default_risk")
        self.assertEqual(plugins.exchange.list_symbols(), ["BTC/USDT:USDT"])
        self.assertEqual(plugins.exchange.fetch_ticker("BTC/USDT:USDT")["symbol"], "BTC/USDT:USDT")
        self.assertEqual(len(plugins.exchange.fetch_ohlcv("BTC/USDT:USDT", "4h", limit=3)), 3)

    def test_build_runtime_plugins_rejects_unknown(self):
        selection = PluginSelection(
            exchange="unknown",
            strategy="wma45_ohlc4",
            regime_filter="wma_regime",
            risk="default_risk",
        )
        with self.assertRaises(ValueError):
            build_runtime_plugins(selection, _DummyBot())


if __name__ == "__main__":
    unittest.main()

import unittest

from aribot.runtime.bootstrap import _apply_market_quote


class _BotStub:
    def __init__(self):
        self.excluded_bases = []
        self.markets = {}
        self.quote_swaps = ["STALE/SYMBOL"]
        self.btc_regime_symbol = None


class BootstrapQuoteApplicationTests(unittest.TestCase):
    def test_apply_market_quote_filters_and_overwrites_symbol_list(self):
        bot = _BotStub()
        bot.excluded_bases = ["DOGE"]
        bot.markets = {
            "BTC/USDC:USDC": {"active": True, "swap": True, "quote": "USDC", "base": "BTC"},
            "DOGE/USDC:USDC": {"active": True, "swap": True, "quote": "USDC", "base": "DOGE"},
            "ETH/USDT:USDT": {"active": True, "swap": True, "quote": "USDT", "base": "ETH"},
        }

        _apply_market_quote(bot, "USDC")

        self.assertEqual(bot.quote_swaps, ["BTC/USDC:USDC"])
        self.assertEqual(bot.btc_regime_symbol, "BTC/USDC:USDC")

    def test_apply_market_quote_clears_list_when_no_match(self):
        bot = _BotStub()
        bot.markets = {
            "ETH/USDT:USDT": {"active": True, "swap": True, "quote": "USDT", "base": "ETH"},
        }

        _apply_market_quote(bot, "USDC")

        self.assertEqual(bot.quote_swaps, [])


if __name__ == "__main__":
    unittest.main()

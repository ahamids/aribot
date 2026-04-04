from __future__ import annotations


class BybitExchangeAdapter:
    """Thin exchange shim around the current bot runtime object."""

    def __init__(self, bot):
        self.bot = bot

    def name(self) -> str:
        return "bybit"

    def list_symbols(self) -> list[str]:
        return list(getattr(self.bot, "quote_swaps", []))

    def fetch_ticker(self, symbol: str):
        return self.bot.exchange.fetch_ticker(symbol)

    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int = 100):
        return self.bot.exchange.fetch_ohlcv(symbol, timeframe, limit=limit)

    def fetch_balance(self):
        return self.bot.exchange.fetch_balance()

from __future__ import annotations


class WMA45OHLC4StrategyAdapter:
    """Strategy shim delegating to current Aribot analysis methods."""

    def __init__(self, bot):
        self.bot = bot

    def name(self) -> str:
        return "wma45_ohlc4"

    def required_candle_count(self) -> int:
        return 47

    def analyze_symbol(self, symbol: str, for_entry: bool = False):
        return self.bot.analyze_market(symbol, for_entry=for_entry)

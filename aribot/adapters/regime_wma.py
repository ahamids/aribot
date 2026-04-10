from __future__ import annotations


class WMARegimeFilterAdapter:
    """Regime shim delegating to current Aribot regime method."""

    def __init__(self, bot):
        self.bot = bot

    def name(self) -> str:
        return "wma_regime"

    def update(self):
        return self.bot.fetch_btc_regime_signal()

    def current_direction(self) -> str:
        return str(getattr(self.bot, "last_regime_signal", "UNAVAILABLE"))

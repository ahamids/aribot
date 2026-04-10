from __future__ import annotations


class DefaultRiskAdapter:
    """Risk shim around existing Aribot risk gate and sizing flow."""

    def __init__(self, bot):
        self.bot = bot

    def name(self) -> str:
        return "default_risk"

    def entry_gate_block_reason(self, now_utc=None):
        return self.bot.entry_gate_block_reason(now_utc=now_utc)

    def refresh_daily_breakers(self):
        self.bot.update_daily_drawdown_pause()

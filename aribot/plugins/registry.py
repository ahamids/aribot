from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PluginSelection:
    exchange: str
    strategy: str
    regime_filter: str
    risk: str


class PluginRegistry:
    def __init__(self):
        self._exchanges: set[str] = set()
        self._strategies: set[str] = set()
        self._regime_filters: set[str] = set()
        self._risks: set[str] = set()

    def register_exchange(self, plugin_id: str) -> None:
        self._exchanges.add(plugin_id.strip())

    def register_strategy(self, plugin_id: str) -> None:
        self._strategies.add(plugin_id.strip())

    def register_regime_filter(self, plugin_id: str) -> None:
        self._regime_filters.add(plugin_id.strip())

    def register_risk(self, plugin_id: str) -> None:
        self._risks.add(plugin_id.strip())

    def ensure_available(self, selection: PluginSelection) -> None:
        self._ensure("exchange", selection.exchange, self._exchanges)
        self._ensure("strategy", selection.strategy, self._strategies)
        self._ensure("regime_filter", selection.regime_filter, self._regime_filters)
        self._ensure("risk", selection.risk, self._risks)

    @staticmethod
    def _ensure(kind: str, plugin_id: str, available: set[str]) -> None:
        if plugin_id not in available:
            choices = ", ".join(sorted(available)) or "<none registered>"
            raise ValueError(f"Unknown {kind} plugin '{plugin_id}'. Available: {choices}")


def build_builtin_registry() -> PluginRegistry:
    """Register currently supported built-ins for config validation."""
    registry = PluginRegistry()
    registry.register_exchange("bybit")
    registry.register_strategy("wma45_ohlc4")
    registry.register_regime_filter("wma_regime")
    registry.register_risk("default_risk")
    return registry

from __future__ import annotations

from dataclasses import dataclass

from aribot.adapters.exchange_bybit import BybitExchangeAdapter
from aribot.adapters.regime_wma import WMARegimeFilterAdapter
from aribot.adapters.risk_default import DefaultRiskAdapter
from aribot.adapters.strategy_wma45_ohlc4 import WMA45OHLC4StrategyAdapter
from aribot.plugins.registry import PluginSelection


@dataclass(frozen=True)
class RuntimePlugins:
    exchange: object
    strategy: object
    regime_filter: object
    risk: object


def build_runtime_plugins(selection: PluginSelection, bot) -> RuntimePlugins:
    exchange = _build_exchange(selection.exchange, bot)
    strategy = _build_strategy(selection.strategy, bot)
    regime_filter = _build_regime_filter(selection.regime_filter, bot)
    risk = _build_risk(selection.risk, bot)
    return RuntimePlugins(exchange=exchange, strategy=strategy, regime_filter=regime_filter, risk=risk)


def _build_exchange(plugin_id: str, bot):
    if plugin_id == "bybit":
        return BybitExchangeAdapter(bot)
    raise ValueError(f"Unsupported exchange plugin: {plugin_id}")


def _build_strategy(plugin_id: str, bot):
    if plugin_id == "wma45_ohlc4":
        return WMA45OHLC4StrategyAdapter(bot)
    raise ValueError(f"Unsupported strategy plugin: {plugin_id}")


def _build_regime_filter(plugin_id: str, bot):
    if plugin_id == "wma_regime":
        return WMARegimeFilterAdapter(bot)
    raise ValueError(f"Unsupported regime filter plugin: {plugin_id}")


def _build_risk(plugin_id: str, bot):
    if plugin_id == "default_risk":
        return DefaultRiskAdapter(bot)
    raise ValueError(f"Unsupported risk plugin: {plugin_id}")

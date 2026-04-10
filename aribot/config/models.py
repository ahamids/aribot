from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict


@dataclass(frozen=True)
class RuntimeConfig:
    profile: str = "usdt"
    mode: str = "paper"
    emoji_mode: str = "noemojis"
    db_path: str = "usdt_bot_v2.db"
    run_migrations: bool = True


@dataclass(frozen=True)
class TradingConfig:
    market_quote: str = "USDT"


@dataclass(frozen=True)
class PluginConfig:
    exchange: str = "bybit"
    strategy: str = "wma45_ohlc4"
    regime_filter: str = "wma_regime"
    risk: str = "default_risk"


@dataclass(frozen=True)
class BotConfig:
    runtime: RuntimeConfig
    trading: TradingConfig
    plugins: PluginConfig
    raw: Dict[str, Any] = field(default_factory=dict)

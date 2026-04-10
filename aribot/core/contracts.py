from __future__ import annotations

from typing import Protocol, Sequence


class ExchangePlugin(Protocol):
    """Exchange adapter contract for runtime orchestration."""

    def name(self) -> str:
        ...


class StrategyPlugin(Protocol):
    """Strategy contract for signal generation."""

    def name(self) -> str:
        ...

    def required_candle_count(self) -> int:
        ...


class RegimeFilterPlugin(Protocol):
    """Regime filter contract for gating entries."""

    def name(self) -> str:
        ...

    def current_direction(self) -> str:
        ...


class RiskPlugin(Protocol):
    """Risk manager contract for sizing and exits."""

    def name(self) -> str:
        ...


class PluginSet(Protocol):
    """Resolved plugin identifiers chosen by configuration."""

    exchange: str
    strategy: str
    regime_filter: str
    risk: str

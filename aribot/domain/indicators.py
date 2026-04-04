from __future__ import annotations

from typing import Iterable, Sequence


def calculate_wma(source_prices: Sequence[float], period: int = 45, offset: int = 2) -> float | None:
    """Compute weighted moving average over source prices with optional offset."""
    if len(source_prices) < period + offset:
        return None

    prices_for_wma = source_prices[:-(offset) if offset > 0 else None]
    if len(prices_for_wma) < period:
        return None

    weights = list(range(1, period + 1))
    return sum(price * weight for price, weight in zip(prices_for_wma[-period:], weights)) / sum(weights)


def calculate_ohlc4(ohlcv_data: Iterable[Sequence[float]]) -> list[float]:
    """Return OHLC4 values from iterable OHLCV candle rows."""
    return [(candle[1] + candle[2] + candle[3] + candle[4]) / 4 for candle in ohlcv_data]

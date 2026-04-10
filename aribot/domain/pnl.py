from __future__ import annotations


def derive_pnl_pct(entry_price, current_price, side):
    """Return price-only PnL percent independent of leverage and margin mode."""
    try:
        ep = float(entry_price)
        cp = float(current_price)
    except (TypeError, ValueError):
        return 0.0

    if ep <= 0.0:
        return 0.0

    normalized_side = str(side or "").strip().lower()
    if normalized_side in {"long", "buy"}:
        return ((cp - ep) / ep) * 100.0
    if normalized_side in {"short", "sell"}:
        return ((ep - cp) / ep) * 100.0

    return 0.0

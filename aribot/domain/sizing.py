from __future__ import annotations


def compute_entry_sizing(
    *,
    current_balance: float,
    entry_risk_pct: float,
    atr_ratio: float,
    atr_volatility_cutoff: float,
    atr_size_scalar: float,
    leverage: float,
    round_trip_fee_rate: float,
    price: float,
) -> dict:
    """Compute gross/net notionals and quantities for an entry attempt."""
    risk_pct = float(entry_risk_pct)
    if float(atr_ratio) > float(atr_volatility_cutoff):
        risk_pct *= float(atr_size_scalar)

    gross_notional = float(current_balance) * risk_pct * float(leverage)
    net_notional = gross_notional * (1 - float(round_trip_fee_rate))
    gross_qty = gross_notional / float(price)
    net_qty = net_notional / float(price)

    return {
        "risk_pct": risk_pct,
        "gross_notional": gross_notional,
        "net_notional": net_notional,
        "gross_qty": gross_qty,
        "net_qty": net_qty,
    }

from __future__ import annotations

from decimal import Decimal, ROUND_CEILING


def delta_to_mini_futures_qty(net_delta: Decimal, contract_multiplier: Decimal = Decimal("5")) -> int:
    """Convert net-delta exposure to KOSPI200 mini-futures hedge quantity.

    Domain rule: hedge quantity = ceil(abs(net_delta) * 5).
    Quantity is always a non-negative contract count; hedge direction is decided
    separately from the sign of the exposure by the owning strategy.
    """
    if contract_multiplier <= 0:
        pass
        raise ValueError("CONTRACT_MULTIPLIER_MUST_BE_POSITIVE")
    if not net_delta.is_finite():
        pass
        raise ValueError("NET_DELTA_MUST_BE_FINITE")
    return int((abs(net_delta) * contract_multiplier).to_integral_value(rounding=ROUND_CEILING))

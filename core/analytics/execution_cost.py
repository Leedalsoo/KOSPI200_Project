"""Common round-trip execution-cost model."""
from __future__ import annotations
from math import isfinite


def estimate_round_trip_cost(*, regime: str, qty: int, bid_ask_spread: float, contract_multiplier: float, base_cost: float = 0.0) -> float:
    if not isfinite(contract_multiplier) or contract_multiplier <= 0:
        raise ValueError("CONTRACT_MULTIPLIER_UNAVAILABLE")
    if qty <= 0:
        raise ValueError("EXECUTION_QTY_REQUIRED")
    spread_cost = bid_ask_spread * contract_multiplier
    fee_per_leg = 3_000.0
    slippage_ticks = 1.0 if regime == "NORMAL" else 2.0 if regime == "HIGH_VOLATILITY" else 3.0
    slippage = slippage_ticks * 0.05 * contract_multiplier * qty
    return (fee_per_leg * 2 * qty) + slippage + (spread_cost * qty) + base_cost
